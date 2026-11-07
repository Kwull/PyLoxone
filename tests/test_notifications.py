"""Miniserver notifications: the ``notifications`` global state.

The JSON shape is the one documented in the structure file (12.0,
"globalStates"): ``{"uid", "ts", "type": 10, "title", "message",
"data": {"lvl", "uuid"?}}``. The fixture's uuid for the state is the
harness's ``globalStates.notifications``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from homeassistant.helpers import entity_registry as er

from custom_components.loxone.const import NOTIFICATION_EVENT
from custom_components.loxone.notifications import notification_state, notifications_state_uuid, parse_notification
from custom_components.loxone.sensor import LoxoneNotificationSensor

NOTIFICATIONS = "4d53676c-616c-6c4e-ffff-4e4f474c31303041"
SERIAL = "TEST-SERIAL-0001"

RAW = json.dumps(
    {
        "uid": "n-1",
        "ts": 1762500000,
        "type": 10,
        "title": "Intercom 4AC",
        "message": "Dzwonek",
        "data": {"lvl": 1, "uuid": "1e5440ea-02c9-b891-ffff52ab80121708"},
    }
)


def test_the_uuid_comes_from_global_states(loxapp3):
    assert notifications_state_uuid(loxapp3) == NOTIFICATIONS
    assert notifications_state_uuid({}) is None
    assert notifications_state_uuid(None) is None


def test_documented_json_is_flattened():
    fields = parse_notification(RAW)
    assert fields["uid"] == "n-1"
    assert fields["ts"] == 1762500000
    assert fields["type"] == 10
    assert fields["title"] == "Intercom 4AC"
    assert fields["message"] == "Dzwonek"
    assert fields["level"] == 1
    assert fields["level_name"] == "info"
    assert fields["control_uuid"] == "1e5440ea-02c9-b891-ffff52ab80121708"
    assert fields["raw"] == RAW
    assert notification_state(fields) == "Intercom 4AC: Dzwonek"


def test_plain_text_is_kept_as_the_message():
    fields = parse_notification("just text")
    assert fields["title"] is None
    assert fields["message"] == "just text"
    assert fields["raw"] == "just text"
    assert notification_state(fields) == "just text"
    assert notification_state(parse_notification('{"title": "Only a title"}')) == "Only a title"
    assert len(notification_state({"title": "t", "message": "m" * 300})) == 255


def test_sensor_shows_the_last_notification():
    entity = LoxoneNotificationSensor(SERIAL, NOTIFICATIONS)
    entity.async_write_ha_state = lambda: None
    assert entity.unique_id == f"{SERIAL}-loxone_last_notification"
    assert entity.native_value is None

    asyncio.run(entity.event_handler(SimpleNamespace(data={"other": "x"})))
    assert entity.native_value is None

    asyncio.run(entity.event_handler(SimpleNamespace(data={NOTIFICATIONS: RAW})))
    assert entity.native_value == "Intercom 4AC: Dzwonek"
    attrs = entity.extra_state_attributes
    assert attrs["uid"] == "n-1"
    assert attrs["level_name"] == "info"
    assert attrs["state_uuid"] == NOTIFICATIONS


async def test_notification_reaches_the_sensor_and_the_event_bus(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", "loxone", f"{SERIAL}-loxone_last_notification")
    assert entity_id, "no notification sensor"
    assert hass.states.get(entity_id).state == "unknown"

    events = []
    hass.bus.async_listen(NOTIFICATION_EVENT, lambda event: events.append(event.data))

    # Through the real listener callback: the bus event comes from there,
    # the sensor from the ``loxone_event`` it fires.
    await mock_connection.callback({NOTIFICATIONS: RAW})
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "Intercom 4AC: Dzwonek"
    assert len(events) == 1
    assert events[0]["miniserver"] == SERIAL
    assert events[0]["title"] == "Intercom 4AC"
    assert events[0]["message"] == "Dzwonek"
    assert events[0]["level_name"] == "info"

    # Any other state does not fire it.
    await mock_connection.callback({"some-other-uuid": 1.0})
    await hass.async_block_till_done()
    assert len(events) == 1
