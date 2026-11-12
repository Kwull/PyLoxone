"""TextState (the "State" block): a text with an icon and a colour.

The fixture's "Parcel Box" has the shape a Miniserver Gen. 2 sends:
``textAndIcon`` (the text, on the control's own uuid) and ``iconAndColor``
(a JSON ``{"icon": "...", "color": "#rrggbb"}``), both as text events.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from homeassistant.helpers import entity_registry as er

from custom_components.loxone.sensor import LoxoneTextStateSensor

PARCEL_BOX = "74657874-0190-d079-ffff-f64756365205000190"
ICON_AND_COLOR = "74657874-0191-d07a-ffff-f64756365205000191"


def _sensor() -> LoxoneTextStateSensor:
    entity = LoxoneTextStateSensor(
        name="Parcel Box",
        uuidAction=PARCEL_BOX,
        room="Parlour",
        cat="",
        type="TextState",
        states={"textAndIcon": PARCEL_BOX, "iconAndColor": ICON_AND_COLOR},
        details={},
    )
    entity.async_write_ha_state = lambda: None
    return entity


def _event(entity, data: dict) -> None:
    asyncio.run(entity.event_handler(SimpleNamespace(data=data)))


def test_text_and_icon_come_from_the_two_text_states():
    entity = _sensor()
    assert entity.native_value is None
    assert entity.unique_id == PARCEL_BOX

    _event(entity, {PARCEL_BOX: "Zamknięty"})
    assert entity.native_value == "Zamknięty"
    attrs = entity.extra_state_attributes
    assert attrs["loxone_icon"] is None
    assert attrs["color"] is None

    _event(entity, {ICON_AND_COLOR: '{"icon":"IconsFilled/window-state-closed-secured.svg","color":"#8DFF70"}'})
    attrs = entity.extra_state_attributes
    assert attrs["loxone_icon"] == "IconsFilled/window-state-closed-secured.svg"
    assert attrs["color"] == "#8DFF70"
    assert attrs["state_uuid"] == PARCEL_BOX
    assert attrs["device_type"] == "TextState"
    # The text survives an icon update.
    assert entity.native_value == "Zamknięty"


def test_bad_icon_json_and_long_text_are_harmless():
    entity = _sensor()
    _event(entity, {ICON_AND_COLOR: "not json"})
    assert entity.extra_state_attributes["loxone_icon"] is None
    _event(entity, {PARCEL_BOX: "x" * 300})
    assert len(entity.native_value) == 255


async def test_text_state_sensor_in_home_assistant(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", "loxone", PARCEL_BOX)
    assert entity_id, "the fixture's TextState did not create a sensor"
    assert hass.states.get(entity_id).state == "unknown"

    mock_connection.feed(PARCEL_BOX, "Zamknięty")
    mock_connection.feed(ICON_AND_COLOR, '{"icon":"i.svg","color":"#8DFF70"}')
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "Zamknięty"
    assert state.attributes["color"] == "#8DFF70"
    assert state.attributes["loxone_icon"] == "i.svg"
