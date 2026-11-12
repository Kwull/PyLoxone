"""
Loxone intercom camera.

One camera per ``IntercomV2`` control that has a ``deviceUuid`` in its
``details``. Two sources, tried in order:

* **Phase 2 — live MJPEG**: the Miniserver's video proxy
  ``/proxy/<uuidAction>/``, authenticated with HTTP Digest (the same
  algorithm the app uses — see ``intercom_digest.py``). A background task
  keeps the stream open and serves the latest frame.
* **Phase 1 — JPEG snapshot** (fallback): ``/proxy/<deviceUuid>/jpg/image.jpg``
  with ``Authorization: Bearer <token>`` — the app's doorbell-thumbnail
  endpoint (``GetIntercomImageUseCase``).

The snapshot is refreshed when the intercom rings (``bell`` 0 -> 1).
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT
from .intercom import intercom_controls, intercom_device_info, is_active
from .intercom_digest import build_digest_header, digest_uri, parse_digest_challenge
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_PATH = "/proxy/{device_uuid}/jpg/image.jpg"
MJPEG_PATH = "/proxy/{uuid_action}/"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_STREAM_RECONNECT_DELAY = 5
_BOUNDARY_RE = re.compile(r'boundary=("?)([^";]+)\1')


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one camera per IntercomV2 with a device UUID."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []
    for control in intercom_controls(loxconfig):
        device_uuid = (control.get("details") or {}).get("deviceUuid")
        if not device_uuid:
            continue
        entities.append(LoxoneIntercomCamera(control, device_uuid))
    async_add_entities(entities)


class LoxoneIntercomCamera(Camera):
    """Intercom video: live MJPEG when available, else a JPEG snapshot."""

    def __init__(self, control: dict, device_uuid: str) -> None:
        super().__init__()
        self._control = control
        self._device_uuid = device_uuid
        self._uuid_action = control.get("uuidAction", "")
        self._latest_frame: bytes | None = None
        self._stream_task: asyncio.Task | None = None
        self._attr_name = f"{control['name']} Camera"
        self._attr_unique_id = f"{control['uuidAction']}-camera"
        self._attr_device_info = intercom_device_info(control)
        self._attr_content_type = "image/jpeg"
        self._attr_extra_state_attributes = {
            "device_uuid": device_uuid,
            "device_serial": (control.get("details") or {}).get("serialNr"),
        }

    # ------------------------------------------------------------------ #
    # connection helpers
    # ------------------------------------------------------------------ #

    def _coordinator(self):
        try:
            return self.hass.data[DOMAIN][self.registry_entry.config_entry_id]
        except (AttributeError, KeyError, TypeError):
            return None

    @property
    def available(self) -> bool:
        """Unavailable while the Loxone connection is down."""
        coordinator = self._coordinator()
        return coordinator is not None and coordinator.connection_available

    def _base_url(self) -> str | None:
        """The reachable Miniserver origin (local host or resolved relay)."""
        coordinator = self._coordinator()
        if coordinator is None or coordinator.api is None or not coordinator.api.url:
            return None
        scheme = coordinator.api.scheme or "http"
        return f"{scheme}://{coordinator.api.url}"

    def _is_remote(self) -> bool:
        base = self._base_url() or ""
        return "dyndns.loxonecloud" in base.lower()

    def _snapshot_url(self) -> str | None:
        base = self._base_url()
        if not base:
            return None
        return base + SNAPSHOT_PATH.format(device_uuid=self._device_uuid)

    def _mjpeg_url(self) -> str | None:
        base = self._base_url()
        if not base or not self._uuid_action:
            return None
        return base + MJPEG_PATH.format(uuid_action=self._uuid_action)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT, self._on_loxone_event))
        self._stream_task = self.hass.async_create_task(self._stream_loop())
        self.async_on_remove(self._cancel_stream)

    def _cancel_stream(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()

    def _on_loxone_event(self, event) -> None:
        """Re-request the image on the start of a ring (``bell`` 0 -> 1)."""
        bell = (self._control.get("states") or {}).get("bell")
        if bell in event.data and is_active(event.data[bell]):
            self.async_write_ha_state()

    # ------------------------------------------------------------------ #
    # image API
    # ------------------------------------------------------------------ #

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Serve the latest MJPEG frame, falling back to the snapshot."""
        if self._latest_frame is not None:
            return self._latest_frame
        return await self._fetch_snapshot()

    # ------------------------------------------------------------------ #
    # Phase 1: JPEG snapshot (Bearer token)
    # ------------------------------------------------------------------ #

    async def _fetch_snapshot(self) -> bytes | None:
        coordinator = self._coordinator()
        if coordinator is None or coordinator.api is None:
            return None
        url = self._snapshot_url()
        if not url:
            return None
        token = coordinator.api.get_token_dict().get("token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
                if resp.status == 200:
                    return await resp.read()
                _LOGGER.debug(
                    "Intercom snapshot returned HTTP %s from %s", resp.status, url
                )
        except Exception as err:  # noqa: BLE001 - a snapshot must never break HA
            _LOGGER.debug("Intercom snapshot failed (%s): %s", url, err)
        return None

    # ------------------------------------------------------------------ #
    # Phase 2: MJPEG stream (HTTP Digest)
    # ------------------------------------------------------------------ #

    async def _stream_loop(self) -> None:
        """Keep the MJPEG stream open and store the latest frame."""
        while True:
            coordinator = self._coordinator()
            if coordinator is None or not coordinator.connection_available:
                await asyncio.sleep(_STREAM_RECONNECT_DELAY)
                continue
            try:
                async for frame in self._iter_mjpeg_frames():
                    self._latest_frame = frame
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect below
                _LOGGER.debug("Intercom MJPEG stream ended (%s); reconnecting", err)
            await asyncio.sleep(_STREAM_RECONNECT_DELAY)

    async def _iter_mjpeg_frames(self):
        url = self._mjpeg_url()
        if not url:
            return
        coordinator = self._coordinator()
        username = coordinator.api.username
        password = coordinator.api.password
        session = async_get_clientsession(self.hass)
        uri = digest_uri(urlparse(url).path or "/", self._is_remote())

        # First request unauthenticated: a 401 carries the Digest challenge.
        async with session.get(url, timeout=_TIMEOUT) as resp:
            if resp.status == 401:
                challenge = parse_digest_challenge(resp.headers.get("WWW-Authenticate", ""))
                if not challenge:
                    _LOGGER.debug("No usable Digest challenge from %s", url)
                    return
                header = build_digest_header(
                    username, password, "GET", uri, challenge
                )
                async for frame in self._stream_frames(
                    session, url, {"Authorization": header}
                ):
                    yield frame
            elif resp.status == 200:
                async for frame in self._stream_frames(session, url, {}):
                    yield frame
            else:
                _LOGGER.debug("Intercom MJPEG returned HTTP %s from %s", resp.status, url)

    async def _stream_frames(self, session, url, headers):
        """Yield JPEG frames from a ``multipart/x-mixed-replace`` response."""
        stream_timeout = aiohttp.ClientTimeout(total=None, sock_read=30)
        async with session.get(url, headers=headers, timeout=stream_timeout) as resp:
            if resp.status != 200:
                _LOGGER.debug("Intercom MJPEG (auth) returned HTTP %s", resp.status)
                return
            boundary = None
            match = _BOUNDARY_RE.search(resp.headers.get("Content-Type", ""))
            if match:
                boundary = ("--" + match.group(2)).encode()
            buffer = b""
            async for chunk in resp.content.iter_chunked(65536):
                buffer += chunk
                if not boundary:
                    continue
                while boundary in buffer:
                    idx = buffer.find(boundary)
                    part = buffer[:idx]
                    buffer = buffer[idx + len(boundary) :]
                    sep = part.find(b"\r\n\r\n")
                    if sep == -1:
                        continue
                    jpeg = part[sep + 4 :].rstrip(b"\r\n")
                    if jpeg:
                        yield jpeg
