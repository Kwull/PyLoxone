"""
Miniserver notifications (the global state ``notifications``).

The structure file lists the uuid under ``globalStates.notifications``. The
Miniserver sends a text event on it for every push notification the user is
allowed to receive (structure file 12.0, "globalStates"): a JSON object

    {"uid": "...", "ts": 1700000000, "type": 10, "title": "...",
     "message": "...", "data": {"lvl": 1, "uuid": "<control uuid, optional>"}}

``type`` 10 is a normal message; ``lvl`` 1 info, 2 error, 3 system error.
It only arrives when a notification happens: it is not part of the initial
state table.

Two things are made of it:

* the Home Assistant event ``loxone_notification`` (see ``__init__.py``),
  with the fields above flattened, for automations;
* the diagnostic sensor "Loxone Last Notification" (``sensor.py``,
  ``LoxoneNotificationSensor``), state ``<title>: <message>``, with the same
  fields as attributes.

This module holds only the parsing: ``__init__.py`` imports it at module
level, so it must not import ``LoxoneEntity`` back from there.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .const import NOTIFICATION_EVENT  # noqa: F401 - re-exported for callers

_LOGGER = logging.getLogger(__name__)

MAX_STATE_LENGTH = 255

LEVELS = {1: "info", 2: "error", 3: "system_error"}


def notifications_state_uuid(loxconfig: dict | None) -> str | None:
    """The uuid of the ``notifications`` global state, if the file has one."""
    if not isinstance(loxconfig, dict):
        return None
    uuid = (loxconfig.get("globalStates") or {}).get("notifications")
    return uuid if isinstance(uuid, str) and uuid else None


def parse_notification(raw: Any) -> dict[str, Any]:
    """
    Flatten one notification text event into plain fields.

    Anything that is not the documented JSON object still yields a dict with
    ``raw`` and the text as ``message``, so a notification is never lost.
    """
    text = raw if isinstance(raw, str) else json.dumps(raw) if isinstance(raw, dict) else str(raw)
    parsed: Any = raw if isinstance(raw, dict) else None
    if parsed is None and isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
    if not isinstance(parsed, dict):
        return {
            "uid": None,
            "ts": None,
            "type": None,
            "title": None,
            "message": text,
            "level": None,
            "level_name": None,
            "control_uuid": None,
            "raw": text,
        }
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
    level = data.get("lvl")
    return {
        "uid": parsed.get("uid"),
        "ts": parsed.get("ts"),
        "type": parsed.get("type"),
        "title": parsed.get("title"),
        "message": parsed.get("message"),
        "level": level,
        "level_name": LEVELS.get(level) if isinstance(level, int) else None,
        "control_uuid": data.get("uuid"),
        "raw": text,
    }


def notification_state(fields: dict[str, Any]) -> str:
    """``<title>: <message>`` (or whichever of the two exists), HA-sized."""
    title = fields.get("title")
    message = fields.get("message")
    state = f"{title}: {message}" if title and message else str(title or message or fields.get("raw") or "")
    return state[:MAX_STATE_LENGTH]
