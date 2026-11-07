"""
Loxone event entities.

One per ``IntercomV2``: the doorbell (device class ``doorbell``), event type
``ring`` whenever a ring starts. See ``intercom.py``.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .intercom import LoxoneDoorbellEvent, intercom_controls
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []

    try:
        entities.extend(LoxoneDoorbellEvent(control) for control in intercom_controls(loxconfig))
    except Exception:
        _LOGGER.exception("Skipping IntercomV2 controls")

    async_add_entities(entities)
