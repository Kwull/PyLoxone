"""
Loxone intercom camera.

One camera per ``IntercomV2`` control that has a ``deviceUuid`` in its
``details``. The image is the Miniserver's video proxy endpoint
``/proxy/<uuid>/jpg/image.jpg``.

Authentication matches what the official app does for live intercom video
(``shared-app.js`` ``_appendLxIntercomAuth``): a seed-based query-string
signature computed from the Miniserver username/password —

    auth = MD5( MD5(user) : seed : MD5(password) )   (uppercase hex)

appended as ``?auth=…&seed=…``. The snapshot is fetched on demand and
refreshed when the intercom rings (``bell`` 0 -> 1).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import string

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT
from .intercom import intercom_controls, intercom_device_info, is_active
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_PATH = "/proxy/{device_uuid}/jpg/image.jpg"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_SEED_ALPHABET = string.ascii_letters + string.digits


def _intercom_stream_auth(user: str, password: str) -> tuple[str, str]:
    """Return ``(auth, seed)`` for the intercom video proxy.

    Mirrors the app's ``_appendLxIntercomAuth``: a 31-char random seed and
    ``auth = MD5( MD5(user) ":" seed ":" MD5(password) )``, uppercase hex.
    """
    seed = "".join(secrets.choice(_SEED_ALPHABET) for _ in range(31))
    h_user = hashlib.md5(user.encode("utf-8")).hexdigest().upper()
    h_pass = hashlib.md5(password.encode("utf-8")).hexdigest().upper()
    auth = hashlib.md5(f"{h_user}:{seed}:{h_pass}".encode("utf-8")).hexdigest().upper()
    return auth, seed


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
    """Intercom still image, served by the Miniserver video proxy."""

    def __init__(self, control: dict, device_uuid: str) -> None:
        super().__init__()
        self._control = control
        self._device_uuid = device_uuid
        self._attr_name = f"{control['name']} Camera"
        self._attr_unique_id = f"{control['uuidAction']}-camera"
        self._attr_device_info = intercom_device_info(control)
        self._attr_content_type = "image/jpeg"
        self._attr_extra_state_attributes = {
            "device_uuid": device_uuid,
            "device_serial": (control.get("details") or {}).get("serialNr"),
        }

    def _coordinator(self):
        try:
            return self.hass.data[DOMAIN][self.registry_entry.config_entry_id]
        except (AttributeError, KeyError, TypeError):
            return None

    @property
    def available(self) -> bool:
        coordinator = self._coordinator()
        return coordinator is not None and coordinator.connection_available

    def _base_url(self) -> str | None:
        coordinator = self._coordinator()
        if coordinator is None or coordinator.api is None or not coordinator.api.url:
            return None
        scheme = coordinator.api.scheme or "http"
        return f"{scheme}://{coordinator.api.url}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT, self._on_loxone_event))

    def _on_loxone_event(self, event) -> None:
        bell = (self._control.get("states") or {}).get("bell")
        if bell in event.data and is_active(event.data[bell]):
            self.async_write_ha_state()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Fetch the current JPEG snapshot from the Miniserver proxy."""
        coordinator = self._coordinator()
        if coordinator is None or coordinator.api is None:
            return None
        base = self._base_url()
        if not base:
            return None
        user = coordinator.api.username
        password = coordinator.api.password
        auth, seed = _intercom_stream_auth(user, password)
        url = (
            base
            + SNAPSHOT_PATH.format(device_uuid=self._device_uuid)
            + f"?auth={auth}&seed={seed}"
        )
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status == 200:
                    return await resp.read()
                _LOGGER.debug(
                    "Intercom snapshot returned HTTP %s from %s", resp.status, url
                )
        except Exception as err:  # noqa: BLE001 - a snapshot must never break HA
            _LOGGER.debug("Intercom snapshot failed (%s): %s", url, err)
        return None
