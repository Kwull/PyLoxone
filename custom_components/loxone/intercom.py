"""
Loxone Intercom Gen. 2 (``IntercomV2``, the "Door Controller" V2 block).

States, as a Miniserver Gen. 2 with Config 17.2 sends them (value states
unless noted):

    bell                 1 while somebody rings, 0 again when the ring ends
    deviceState          1 when the intercom device is online
    muted                1 when the bell is muted
    answers              text: JSON list of the quick replies the resident can send
    address              text: the intercom's IP address
    version              text: the intercom firmware
    videoSettingsIntern / videoSettingsExtern / bellPreviewMode   numbers
    jLocked              text: lock state of the control (``details.jLockable``)

``subControls`` are plain ``Pushbutton`` controls (``uuidAction`` ``<uuid>/1``,
``<uuid>/2``, ...): the door openers shown during a call.

Entities, all on one device per intercom:

* ``binary_sensor`` "<name> Bell", device class ``sound``: on while it rings.
  The quick replies, the address, the firmware and the mute state are its
  attributes.
* ``event`` "<name> Doorbell", device class ``doorbell``, event type ``ring``
  on every 0 -> 1 of ``bell``: the entity to trigger automations on.
* ``binary_sensor`` "<name> Online" (diagnostic), device class ``connectivity``.
* ``button`` "<name> <sub-control name>" per sub-control (``pulse``).

No camera: ``jdev/sps/io/<uuid>/securedDetails`` (the V1 ``Intercom`` way to
the video stream) answers ``{}`` for an ``IntercomV2``; the Gen. 2 intercom
streams WebRTC to the Loxone app, and its own MJPEG endpoint sits on the
intercom's LAN address, which a remote Miniserver connection cannot reach.
"""

from __future__ import annotations

import json
import logging
import re
from functools import cached_property
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.helpers.entity import EntityCategory

from . import LoxoneEntity
from .button import LoxoneButton
from .helpers import get_all, get_or_create_device

_LOGGER = logging.getLogger(__name__)

INTERCOM_V2_TYPE = "IntercomV2"
EVENT_RING = "ring"

# Loxone uuids are 8-4-4-16 hex groups; the test fixtures use 8-4-4-4-18.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f-]+$", re.IGNORECASE)


def _resolve_name(loxconfig: dict, table: str, value: Any) -> str:
    """
    Room or category name for ``value``.

    ``add_room_and_cat_to_value_values`` rewrites the uuid in the structure
    file to the name in place, so a control another platform set up first
    already carries the name: keep it. An unknown uuid becomes "".
    """
    if not isinstance(value, str) or not value:
        return ""
    entry = (loxconfig.get(table) or {}).get(value)
    if isinstance(entry, dict):
        return entry.get("name", "")
    return "" if _UUID_RE.match(value) else value


def intercom_controls(loxconfig: dict) -> list[dict]:
    """
    Every ``IntercomV2`` control, with the room and category as names.

    Returns copies: the structure file stays as it is for the other
    platforms (several of them build entities from the same control).
    """
    controls = []
    for control in get_all(loxconfig, INTERCOM_V2_TYPE):
        if not isinstance(control, dict) or not control.get("uuidAction"):
            continue
        copy = dict(control)
        copy["room"] = _resolve_name(loxconfig, "rooms", control.get("room"))
        copy["cat"] = _resolve_name(loxconfig, "cats", control.get("cat"))
        copy["states"] = dict(control.get("states") or {})
        copy["details"] = dict(control.get("details") or {})
        copy["subControls"] = dict(control.get("subControls") or {})
        controls.append(copy)
    return controls


def intercom_device_info(control: dict) -> dict:
    """The one HA device all entities of an intercom belong to."""
    return get_or_create_device(control["uuidAction"], control["name"], INTERCOM_V2_TYPE, control.get("room", ""))


def _entity_kwargs(control: dict, suffix: str) -> dict:
    return {
        "name": f"{control['name']} {suffix}",
        "uuidAction": control["uuidAction"],
        "room": control.get("room", ""),
        "cat": control.get("cat", ""),
        "type": INTERCOM_V2_TYPE,
        "states": control.get("states", {}),
        "details": control.get("details", {}),
    }


def is_active(value: Any) -> bool:
    """A Loxone value state read as on/off (``1.0`` on, ``0.0`` off)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "0.0", "off", "false")
    return False


def parse_answers(value: Any) -> list[str]:
    """The ``answers`` text state: a JSON list of quick-reply texts."""
    if isinstance(value, list):
        return [str(x) for x in value]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return [value]
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return [str(parsed)]


class _IntercomEntity(LoxoneEntity):
    """Common part: the intercom device, a suffixed unique id."""

    _attr_should_poll = False

    def __init__(self, control: dict, suffix: str, unique_suffix: str):
        super().__init__(**_entity_kwargs(control, suffix))
        self._control = control
        self._attr_unique_id = f"{control['uuidAction']}-{unique_suffix}"
        self._attr_device_info = intercom_device_info(control)

    @cached_property
    def unique_id(self) -> str:
        return self._attr_unique_id

    def _state_uuid(self, key: str) -> str | None:
        uuid = self.states.get(key)
        return uuid if isinstance(uuid, str) and uuid else None


class LoxoneIntercomBell(_IntercomEntity, BinarySensorEntity):
    """On while somebody rings; the intercom's details as attributes."""

    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_icon = "mdi:doorbell"

    def __init__(self, control: dict):
        super().__init__(control, "Bell", "bell")
        self._attr_is_on = None
        self._answers: list[str] = []
        self._address: str | None = None
        self._version: str | None = None
        self._muted: bool | None = None

    async def event_handler(self, e):
        data = e.data
        changed = False
        bell = self._state_uuid("bell")
        if bell in data:
            self._attr_is_on = is_active(data[bell])
            changed = True
        answers = self._state_uuid("answers")
        if answers in data:
            self._answers = parse_answers(data[answers])
            changed = True
        address = self._state_uuid("address")
        if address in data:
            self._address = str(data[address]) or None
            changed = True
        version = self._state_uuid("version")
        if version in data:
            self._version = str(data[version]) or None
            changed = True
        muted = self._state_uuid("muted")
        if muted in data:
            self._muted = is_active(data[muted])
            changed = True
        if changed:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        details = self._control.get("details", {})
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self._state_uuid("bell"),
            "device_type": INTERCOM_V2_TYPE,
            "answers": list(self._answers),
            "address": self._address,
            "version": self._version,
            "muted": self._muted,
            "device_serial": details.get("serialNr"),
            "device_uuid": details.get("deviceUuid"),
        }


class LoxoneIntercomOnline(_IntercomEntity, BinarySensorEntity):
    """The intercom device's link to the Miniserver (``deviceState``)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, control: dict):
        super().__init__(control, "Online", "online")
        self._attr_is_on = None

    async def event_handler(self, e):
        state = self._state_uuid("deviceState")
        if state in e.data:
            self._attr_is_on = is_active(e.data[state])
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self._state_uuid("deviceState"),
            "device_type": INTERCOM_V2_TYPE,
        }


class LoxoneDoorbellEvent(_IntercomEntity, EventEntity):
    """``ring`` on every start of a ring (``bell`` 0 -> 1)."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [EVENT_RING]

    def __init__(self, control: dict):
        super().__init__(control, "Doorbell", "doorbell")
        self._ringing = False

    async def event_handler(self, e):
        bell = self._state_uuid("bell")
        if bell not in e.data:
            return
        ringing = is_active(e.data[bell])
        if ringing and not self._ringing:
            self._trigger_event(EVENT_RING)
            self.async_write_ha_state()
        self._ringing = ringing

    @property
    def extra_state_attributes(self):
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self._state_uuid("bell"),
            "device_type": INTERCOM_V2_TYPE,
        }


class LoxoneIntercomButton(LoxoneButton):
    """A door opener of the intercom: a ``Pushbutton`` sub-control."""

    def __init__(self, control: dict, sub: dict):
        super().__init__(
            name=f"{control['name']} {sub.get('name', '')}".strip(),
            uuidAction=sub["uuidAction"],
            room=control.get("room", ""),
            cat=control.get("cat", ""),
            type="Pushbutton",
            states=dict(sub.get("states") or {}),
            details=dict(sub.get("details") or {}),
        )
        self._attr_icon = "mdi:door-open"
        self._intercom_device = intercom_device_info(control)

    @property
    def device_info(self):
        return self._intercom_device


def intercom_buttons(control: dict) -> list[LoxoneIntercomButton]:
    """One button per ``Pushbutton`` sub-control, in structure-file order."""
    buttons = []
    for key, sub_control in (control.get("subControls") or {}).items():
        if not isinstance(sub_control, dict) or sub_control.get("type") != "Pushbutton":
            continue
        sub = dict(sub_control)
        sub.setdefault("uuidAction", key)
        buttons.append(LoxoneIntercomButton(control, sub))
    return buttons
