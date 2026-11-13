"""Cloud DNS: remember the relay, go there first, ask Cloud DNS only if it fails.

``https://dns.loxonecloud.com/<serial>`` answers the first bootstrap GET with a
redirect to the Miniserver's relay, ``https://<ip>.<serial>.dyndns.loxonecloud.com:<port>``.
The relay is remembered (``relay_url`` / ``relay_change_callback``, persisted by
the integration in ``ConfigEntry.data``) and tried first on the next open, with
one short try; Cloud DNS is only asked when the relay does not answer or answers
for another Miniserver.

The fake session below plays both: Cloud DNS (answers with the relay as the
final URL, as aiohttp reports after following the redirect) and the relay.
"""

from __future__ import annotations

import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.loxone.const import CONF_RELAY_URL
from custom_components.loxone.pyloxone_api.connection import LoxoneConnection, is_cloud_host, normalize_serial

SERIAL = "001122AABBCC"
CLOUD_DNS = f"https://dns.loxonecloud.com/{SERIAL}"
CONNECT = f"https://connect.loxonecloud.com/{SERIAL}"
CLOUD_HOSTS = (CLOUD_DNS, CONNECT)
# Hostnames come back lower-cased from URL parsing, as they do in real life.
RELAY = f"https://168-119-185-175.{SERIAL.lower()}.dyndns.loxonecloud.com:44675"
NEW_RELAY = f"https://168-119-185-176.{SERIAL.lower()}.dyndns.loxonecloud.com:44680"


def _ll(value: str, control: str = "dev/cfg/apiKey") -> bytes:
    return json.dumps({"LL": {"code": 200, "control": control, "value": value}}).encode()


class _Response:
    status = 200

    def __init__(self, body: bytes, url: str) -> None:
        self._body = body
        self.url = url
        self.content = self

    async def read(self) -> bytes:
        return self._body


class _CM:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self._response

    async def __aexit__(self, *args):
        return None


class _CloudSession:
    """Cloud DNS + relays. ``relay`` is where Cloud DNS points now;
    ``dead`` relays refuse connections; ``serials`` lets a relay answer for
    another Miniserver."""

    closed = False

    def __init__(self, relay: str, *, dead: tuple[str, ...] = (), serials: dict | None = None) -> None:
        from Crypto.PublicKey import RSA

        pem = RSA.generate(1024).publickey().export_key().decode()
        self.cert = pem.replace("BEGIN PUBLIC KEY", "BEGIN CERTIFICATE").replace("END PUBLIC KEY", "END CERTIFICATE")
        self.relay = relay
        self.dead = dead
        self.serials = serials or {}
        self.calls: list[str] = []

    def _api_key(self, base: str) -> bytes:
        snr = self.serials.get(base, "00:11:22:AA:BB:CC")
        return _ll(json.dumps({"version": "17.2.10.21", "snr": snr, "local": False}).replace('"', "'"))

    def get(self, url, **kwargs):
        self.calls.append(url)
        for cloud in CLOUD_HOSTS:
            if url.startswith(cloud):
                # The connect service redirects; aiohttp follows and reports
                # the final URL.
                if self.relay in self.dead:
                    return _CM(error=ConnectionError(f"refused: {self.relay}"))
                path = url[len(cloud) :]
                return self._serve(self.relay, path)
        for base in (RELAY, NEW_RELAY):
            if url.startswith(base):
                if base in self.dead:
                    return _CM(error=ConnectionError(f"refused: {base}"))
                return self._serve(base, url[len(base) :])
        return _CM(error=ConnectionError(f"unknown host {url}"))

    def _serve(self, base: str, path: str):
        final = base + path
        if "apiKey" in path:
            return _CM(_Response(self._api_key(base), final))
        if "LoxAPP3" in path:
            return _CM(_Response(json.dumps({"msInfo": {"serialNr": SERIAL}}).encode(), final))
        return _CM(_Response(_ll(self.cert, "dev/sys/getPublicKey"), final))


def _conn(relay_url: str | None = None, seen: list | None = None) -> LoxoneConnection:
    return LoxoneConnection(
        host=CLOUD_DNS,
        port=443,
        username="user",
        password="pass",
        relay_url=relay_url,
        relay_change_callback=(seen.append if seen is not None else None),
    )


def _hosts(session: _CloudSession) -> list[str]:
    return ["cloud" if any(c.startswith(h) for h in CLOUD_HOSTS) else c.split("/")[2] for c in session.calls]


def test_helpers():
    assert is_cloud_host("dns.loxonecloud.com")
    assert is_cloud_host("DNS.LoxoneCloud.com.")
    assert is_cloud_host("connect.loxonecloud.com")
    assert is_cloud_host("CONNECT.LoxoneCloud.com.")
    assert not is_cloud_host("168-119-185-175.001122AABBCC.dyndns.loxonecloud.com")
    assert not is_cloud_host("192.168.1.10")
    assert normalize_serial("00:11:22:AA:BB:CC") == SERIAL
    assert normalize_serial("001122aabbcc") == SERIAL


async def test_connect_entry_point_remembers_the_relay():
    """The current entry point (``connect.loxonecloud.com``) works like the
    legacy Cloud DNS host: 307 redirect to the relay, which is remembered."""
    session = _CloudSession(RELAY)
    seen: list[str] = []
    conn = LoxoneConnection(
        host=CONNECT,
        port=443,
        username="user",
        password="pass",
        relay_change_callback=seen.append,
    )
    await conn.open(session, connect_websocket=False)

    assert _hosts(session)[0] == "cloud"
    assert all("dyndns" in c for c in session.calls[1:])
    assert conn.relay_url == RELAY
    assert seen == [RELAY]


async def test_first_setup_asks_cloud_dns_and_remembers_the_relay():
    session = _CloudSession(RELAY)
    seen: list[str] = []
    conn = _conn(seen=seen)
    await conn.open(session, connect_websocket=False)

    assert _hosts(session)[0] == "cloud"
    # The rest of the bootstrap went to the relay.
    assert all("dyndns" in c for c in session.calls[1:])
    assert conn.relay_url == RELAY
    assert seen == [RELAY]


async def test_known_relay_is_used_without_cloud_dns():
    session = _CloudSession(RELAY)
    seen: list[str] = []
    conn = _conn(RELAY, seen)
    await conn.open(session, connect_websocket=False)

    assert "cloud" not in _hosts(session)
    assert conn.relay_url == RELAY
    assert seen == []  # unchanged, nothing to persist
    assert conn.scheme == "https"
    assert conn.url == RELAY.removeprefix("https://")


async def test_moved_relay_falls_back_to_cloud_dns_and_remembers_the_new_one():
    session = _CloudSession(NEW_RELAY, dead=(RELAY,))
    seen: list[str] = []
    conn = _conn(RELAY, seen)
    await conn.open(session, connect_websocket=False)

    hosts = _hosts(session)
    assert hosts[0] == RELAY.split("/")[2]  # one try at the old relay
    assert hosts[1] == "cloud"
    assert hosts.count(RELAY.split("/")[2]) == 1
    assert conn.relay_url == NEW_RELAY
    assert seen == [NEW_RELAY]


async def test_relay_answering_for_another_miniserver_is_not_used():
    session = _CloudSession(RELAY, serials={NEW_RELAY: "AA:BB:CC:DD:EE:FF"})
    seen: list[str] = []
    conn = _conn(NEW_RELAY, seen)
    await conn.open(session, connect_websocket=False)

    assert _hosts(session)[1] == "cloud"
    assert conn.relay_url == RELAY
    assert seen == [RELAY]


async def test_reconnect_after_the_relay_moved_goes_back_to_cloud_dns():
    """Within one session too: the old code kept the relay as its only address."""
    session = _CloudSession(RELAY)
    conn = _conn()
    await conn.open(session, connect_websocket=False)
    assert conn.relay_url == RELAY

    session.relay = NEW_RELAY
    session.dead = (RELAY,)
    session.calls.clear()
    await conn.open(session, connect_websocket=False)
    assert _hosts(session)[:2] == [RELAY.split("/")[2], "cloud"]
    assert conn.relay_url == NEW_RELAY


async def test_cloud_dns_failure_is_still_an_error(monkeypatch):
    original = LoxoneConnection._get_with_retry

    async def one_try(self, url, connector, **kwargs):
        kwargs["max_tries"] = 1
        return await original(self, url, connector, **kwargs)

    monkeypatch.setattr(LoxoneConnection, "_get_with_retry", one_try)
    session = _CloudSession(RELAY, dead=(RELAY,))
    conn = _conn(RELAY)
    # Cloud DNS points at the dead relay as well: nothing answers.
    with pytest.raises((ConnectionError, OSError, RuntimeError)):
        await conn._fetch_api_key(session)


async def test_local_address_is_left_alone():
    conn = LoxoneConnection(host="192.168.1.10", port=80, username="u", password="p", relay_url=RELAY)
    assert conn.relay_url is None
    assert conn._bootstrap_candidates() == [("http", "192.168.1.10", False)]


async def test_coordinator_persists_the_relay_in_entry_data(hass):
    from custom_components.loxone.coordinator import LoxoneCoordinator

    entry = MockConfigEntry(
        domain="loxone",
        version=4,
        data={"token": "t", "hash_alg": "SHA256", "valid_until": 1},
        options={"host": CLOUD_DNS, "port": 443, "username": "u", "password": "p"},
    )
    entry.add_to_hass(hass)
    coordinator = LoxoneCoordinator(hass, entry)
    coordinator._on_relay_changed(RELAY)
    assert entry.data[CONF_RELAY_URL] == RELAY
    assert entry.data["token"] == "t"  # the token is kept
