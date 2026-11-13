"""IntercomV2 (Loxone Intercom Gen. 2 / Door Controller V2).

The fixture's "Entrance Intercom" has the shape a Miniserver Gen. 2 with
Config 17.2 sends: the value states ``bell``, ``deviceState``, ``muted``,
the text states ``answers`` (a JSON list), ``address``, ``version``, and two
``Pushbutton`` sub-controls (``<uuid>/1`` Wicket, ``<uuid>/2`` Gate).

Expected values are literals read from ``tests/fixtures/LoxAPP3_harness.json``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers import entity_registry as er

from custom_components.loxone.intercom import (
    LoxoneDoorbellEvent,
    LoxoneIntercomBell,
    LoxoneIntercomOnline,
    intercom_buttons,
    intercom_controls,
    is_active,
    parse_answers,
)

INTERCOM = "696e7463-0170-9747-ffff-f64756365205000170"
BELL = "696e7463-0174-b8a6-ffff-f64756365205000174"
DEVICE_STATE = "696e7463-0178-b8a9-ffff-f64756365205000178"
MUTED = "696e7463-0173-b893-ffff-f64756365205000173"
ANSWERS = "696e7463-0177-b8a8-ffff-f64756365205000177"
ADDRESS = "696e7463-0176-b8a7-ffff-f64756365205000176"
VERSION = "696e7463-0175-b8a5-ffff-f64756365205000175"
WICKET = INTERCOM + "/1"
GATE = INTERCOM + "/2"


def _control(loxapp3: dict) -> dict:
    return next(c for c in intercom_controls(loxapp3) if c["uuidAction"] == INTERCOM)


def _event(entity, data: dict) -> None:
    asyncio.run(entity.event_handler(SimpleNamespace(data=data)))


def _quiet(entity):
    entity.async_write_ha_state = lambda: None
    return entity


def test_controls_carry_names_and_leave_the_structure_file_alone(loxapp3):
    control = _control(loxapp3)
    assert control["room"] == "Parlour"
    assert control["name"] == "Entrance Intercom"
    assert [sub["name"] for sub in control["subControls"].values()] == ["Wicket", "Gate"]
    # Other platforms resolve the same control: the uuid must still be there.
    assert loxapp3["controls"][INTERCOM]["room"].startswith("726f6f6d-")


def test_a_control_already_resolved_by_another_platform_keeps_its_room(loxapp3):
    resolved = dict(loxapp3["controls"][INTERCOM], room="Parlour", cat="Lighting")
    config = {**loxapp3, "controls": {INTERCOM: resolved}}
    control = _control(config)
    assert control["room"] == "Parlour"
    assert control["cat"] == "Lighting"


def test_bell_follows_the_bell_state_and_collects_the_details(loxapp3):
    entity = _quiet(LoxoneIntercomBell(_control(loxapp3)))
    assert entity.unique_id == f"{INTERCOM}-bell"
    assert entity.name == "Entrance Intercom Bell"
    assert entity.is_on is None  # unknown until the first value

    _event(entity, {BELL: 1.0})
    assert entity.is_on is True
    _event(entity, {BELL: 0.0})
    assert entity.is_on is False

    _event(
        entity,
        {
            ANSWERS: '["Nie ma nas w domu.","Jesteśmy w ogrodzie."]',
            ADDRESS: "192.168.10.51",
            VERSION: "17.0.6.1",
            MUTED: 0.0,
        },
    )
    attrs = entity.extra_state_attributes
    assert attrs["answers"] == ["Nie ma nas w domu.", "Jesteśmy w ogrodzie."]
    assert attrs["address"] == "192.168.10.51"
    assert attrs["version"] == "17.0.6.1"
    assert attrs["muted"] is False
    assert attrs["device_serial"] == "001122AABBDD"
    assert attrs["state_uuid"] == BELL
    assert attrs["device_type"] == "IntercomV2"
    assert attrs["room"] == "Parlour"

    # Another control's state does not touch it.
    _event(entity, {DEVICE_STATE: 1.0})
    assert entity.is_on is False


def test_online_follows_device_state(loxapp3):
    entity = _quiet(LoxoneIntercomOnline(_control(loxapp3)))
    assert entity.unique_id == f"{INTERCOM}-online"
    assert entity.is_on is None
    _event(entity, {DEVICE_STATE: 1.0})
    assert entity.is_on is True
    _event(entity, {DEVICE_STATE: 0.0})
    assert entity.is_on is False


def test_doorbell_event_fires_once_per_ring(loxapp3):
    entity = _quiet(LoxoneDoorbellEvent(_control(loxapp3)))
    fired: list[str] = []
    entity._trigger_event = lambda event_type, attributes=None: fired.append(event_type)
    assert entity.unique_id == f"{INTERCOM}-doorbell"

    _event(entity, {BELL: 0.0})
    assert fired == []
    _event(entity, {BELL: 1.0})
    _event(entity, {BELL: 1.0})  # still the same ring
    assert fired == ["ring"]
    _event(entity, {BELL: 0.0})
    _event(entity, {BELL: 1.0})
    assert fired == ["ring", "ring"]


def test_one_button_per_pushbutton_sub_control_on_the_intercom_device(loxapp3):
    control = _control(loxapp3)
    buttons = intercom_buttons(control)
    assert [b.name for b in buttons] == ["Entrance Intercom Wicket", "Entrance Intercom Gate"]
    assert [b.unique_id for b in buttons] == [WICKET, GATE]
    for button in buttons:
        assert button.device_info["identifiers"] == {("loxone", INTERCOM)}
        assert button.device_info["model"] == "IntercomV2"

    # A sub-control of another type is not a button.
    other = dict(control, subControls={**control["subControls"], "x": {"type": "Switch", "name": "No"}})
    assert len(intercom_buttons(other)) == 2


def test_value_and_answers_parsing():
    for on in (1.0, 2, True, "1"):
        assert is_active(on), on
    for off in (0.0, "", None, "off"):
        assert not is_active(off), off
    assert parse_answers('["a", "b"]') == ["a", "b"]
    assert parse_answers(["a"]) == ["a"]
    assert parse_answers("plain text") == ["plain text"]
    assert parse_answers("") == []
    assert parse_answers(None) == []


async def test_intercom_entities_in_home_assistant(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    registry = er.async_get(hass)
    bell_id = registry.async_get_entity_id("binary_sensor", "loxone", f"{INTERCOM}-bell")
    online_id = registry.async_get_entity_id("binary_sensor", "loxone", f"{INTERCOM}-online")
    event_id = registry.async_get_entity_id("event", "loxone", f"{INTERCOM}-doorbell")
    wicket_id = registry.async_get_entity_id("button", "loxone", WICKET)
    for entity_id in (bell_id, online_id, event_id, wicket_id):
        assert entity_id, dict(registry.entities)

    # One device for all of them.
    devices = {registry.async_get(eid).device_id for eid in (bell_id, online_id, event_id, wicket_id)}
    assert len(devices) == 1

    mock_connection.feed(BELL, 1.0)
    await hass.async_block_till_done()
    assert hass.states.get(bell_id).state == STATE_ON
    event_state = hass.states.get(event_id)
    assert event_state.attributes["event_type"] == "ring"
    assert event_state.state != "unknown"

    mock_connection.feed(BELL, 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(bell_id).state == STATE_OFF

    mock_connection.feed(DEVICE_STATE, 1.0)
    await hass.async_block_till_done()
    assert hass.states.get(online_id).state == STATE_ON

    # Pressing the door opener pulses the sub-control's uuidAction.
    await hass.services.async_call("button", "press", {"entity_id": wicket_id}, blocking=True)
    await hass.async_block_till_done()
    assert {"uuid": WICKET, "value": "pulse", "code": None} in mock_connection.sent
