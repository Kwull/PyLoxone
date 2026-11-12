# PyLoxone
![Installs](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=Installations&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.loxone.total)
[![Version](https://img.shields.io/github/manifest-json/v/Kwull/PyLoxone/master?filename=custom_components%2Floxone%2Fmanifest.json&label=version)](https://github.com/Kwull/PyLoxone/commits/master)
[![Hassfest](https://img.shields.io/github/actions/workflow/status/Kwull/PyLoxone/hassfest.yaml?branch=master&label=hassfest)](https://github.com/Kwull/PyLoxone/actions/workflows/hassfest.yaml)
[![HACS](https://img.shields.io/github/actions/workflow/status/Kwull/PyLoxone/validate.yaml?branch=master&label=HACS)](https://github.com/Kwull/PyLoxone/actions/workflows/validate.yaml)
[![Marketplace](https://img.shields.io/badge/Marketplace-Custom-orange.svg)](https://next.home-assistant.io/integrations/marketplace/)


Home Assistant binding for Loxone. 

A special thanks to Pawel Pieczul from the great openhab2 house automation software. 
He really helped me a lot to with the new token based authentication. Thanks Pawel!!!

#### This release works for the version 2024.1.0 and newer!!


## Config for the gen2 miniserver
If you have the gen2 miniserver you should connect via local access. It is more reliable and faster than a cloud connection.

### Config for cloud connection
Please use this only in case local access is not possible.

Example:
- Miniserver Ip: https://connect.loxonecloud.com/123456789ABC
- Port: 443

Change 123456789ABC to your miniserver Serial Number.

> Since Miniserver firmware 16.3 (enforced with the Nov 2026 security update)
> Loxone serves Remote Connect through `connect.loxonecloud.com`. The old
> `dns.loxonecloud.com` entry point is retired and now answers 403
> "Request not permitted", so use `connect.loxonecloud.com`.

## Manual installation
1. Download the zip file and extract all files.
2. Copy the ***custom_components*** folder in the same folder where your configuration.yaml is located
3. Restart Home-Assistant
4. Go to Configuration -> Integrations and search for Pyloxone
5. Add the Integration and fill out all required fields
6. Restart Home-Assistant

## Marketplace installation (Home Assistant 2026.11 and newer)
HACS is built into Home Assistant as the Marketplace since 2026.11, so there is nothing to download.
1. Go to **Settings** > **Marketplace**.
2. In the upper-right corner, select **Add from link**.
3. Under **GitHub link**, enter `https://github.com/Kwull/PyLoxone` and select **Add**.
   If asked, connect the Marketplace to GitHub (device code sign-in), and pick **Integration** as the type.
4. Open PyLoxone in the list, select **Install**, check the version and select **Install** again.
5. Restart Home Assistant if asked (a repair under **Settings** > **System** > **Repairs** can do it).
6. Go to **Settings** > **Devices & services** > **Add integration** and search for PyLoxone.
7. Fill out all required fields.

See the [Marketplace documentation](https://next.home-assistant.io/integrations/marketplace/).
On Home Assistant 2026.10 and older, install [HACS](https://hacs.xyz/docs/use/download/download/) first and add
`https://github.com/Kwull/PyLoxone` as a custom repository (type Integration).

## Supported Loxone Entities
Currently, this integration supports the following Loxone entities by mapping them to Home Assistant entities.
If you encounter a Loxone entity that is currently not supported, you can post a feature request so it can be looked into.

- InfoOnlyAnalog and InfoOnlyDigital
- Switch, TimedSwitch and Pushbutton
- Jalousie, Window and Gate
- Intercom
- IntercomV2 (Loxone Intercom Gen. 2): bell, doorbell event, online state, door-opener buttons
- LightControllerV2
- Alarm
- Fan
- RoomController and RoomControllerV2
- AudioZoneV2
- Slider and ValueSelector (Up-Down Buttons)
- TextInput
- TextState (the "State" block: text, icon and colour)
- Radio Buttons
- Miniserver notifications (event `loxone_notification` and the sensor "Loxone Last Notification")

## Remote Connect: the relay is remembered

With a Remote Connect address (`https://connect.loxonecloud.com/<serial>`), Loxone's connect service answers with a
307 redirect to the Miniserver's relay (`https://<ip>.<serial>.dyndns.loxonecloud.com:<port>`). The integration
remembers that relay in the config entry (next to the token) and goes there first on every setup, reload, restart and
reconnect, with one 10-second try. The connect service is only asked when the relay does not answer or answers for
another Miniserver (a new public IP or port), and the new relay is remembered again. So the connect service is needed
only when the relay moves, not on every setup.

## IntercomV2 (Loxone Intercom Gen. 2)

One device per intercom with:

- `binary_sensor.<name>_bell` (device class *sound*): on while somebody rings. Attributes: the quick replies
  (`answers`), the intercom's `address`, `version`, `muted`, `device_serial`.
- `event.<name>_doorbell` (device class *doorbell*): event type `ring` at the start of every ring. Trigger
  automations on this one.
- `binary_sensor.<name>_online` (diagnostic): the intercom device's link to the Miniserver.
- One `button` per sub-control (the door openers shown during a call), e.g. `button.<name>_gate`.

```yaml
automation:
  - alias: Someone rings at the gate
    triggers:
      - trigger: state
        entity_id: event.entrance_intercom_doorbell
    actions:
      - action: notify.mobile_app_my_phone
        data:
          message: Someone is at the gate
```

No camera entity: an `IntercomV2` answers `jdev/sps/io/<uuid>/securedDetails` with `{}` (the V1 `Intercom` way
to the stream), the Gen. 2 intercom streams WebRTC to the Loxone app through the Miniserver
(`wss://<miniserver>/proxy/<deviceUuid>/`), and its own MJPEG endpoint sits on the intercom's LAN address.
For video in Home Assistant use a bridge such as
[loxone-intercom2](https://github.com/markuslaube/loxone-intercom2) (WebRTC to go2rtc), which also works
through Loxone Cloud DNS.

## TextState

A `TextState` ("State" block) is a sensor whose state is the text; the attributes `loxone_icon` and `color`
carry what the block shows next to it.

## Miniserver notifications

Every push notification the Miniserver sends to the configured user also reaches Home Assistant (the
`notifications` global state):

- the event `loxone_notification` with `miniserver` (serial), `uid`, `ts`, `type`, `title`, `message`,
  `level` (1 info, 2 error, 3 system error), `level_name`, `control_uuid` and `raw`;
- the diagnostic sensor "Loxone Last Notification" (state `<title>: <message>`, the same fields as attributes).

```yaml
automation:
  - alias: Forward Loxone notifications
    triggers:
      - trigger: event
        event_type: loxone_notification
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "{{ trigger.event.data.title }}"
          message: "{{ trigger.event.data.message }}"
```

## Known Limitations

- Pushbuttons are stateless. They can not be used to reliably trigger automations. Use a Switch as a workaround and turn it off again in the Automation or in Loxone itself.

## LightControllerV2 Sub-Controls

Each `LightControllerV2` in Loxone groups individual lighting outputs (dimmers, color pickers, switches) as sub-controls. These are registered in the Home Assistant entity registry but **disabled by default** to keep the UI clean.

To access individual light outputs:

1. Open **Settings → Devices & Services → Entities**
2. Filter by your LightControllerV2 device
3. Enable the sub-control entities you want to use (dimmer, color picker, etc.)

The integration option **"Generate sub-controls for LightControllerV2"** controls the default enabled state for newly created sub-control entities. When enabled, new sub-controls start as enabled; when disabled (the default), they start as disabled but remain visible in the entity registry for manual activation.

## Sensor Device Class Detection

Sensors (InfoOnlyAnalog, Meter) are automatically classified based on their unit and Loxone category/name. The following device classes are detected:

| Device class | Detected by |
|---|---|
| `temperature` | Unit: °C, °F |
| `humidity` | Unit: % **and** category or name contains "humidity", "vlhkost", "feucht", or "humidité" |
| `battery` | Unit: % **and** name contains "batt", "akku", or "battery" |
| `energy` | Unit: kWh, Wh, MWh |
| `power` | Unit: W, kW |
| `volume_flow_rate` | Unit: L/h, L/min |
| `water` | Unit: L |
| `illuminance` | Unit: lx, Lx, lux |
| `carbon_dioxide` | Unit: ppm |
| `wind_speed` | Unit: km/h |

Sensors with `%` unit that don't match any keyword are left without a device class.

### Overriding the detected device class

If the automatic detection assigns the wrong device class (or you want to set one for an unclassified sensor), use Home Assistant's built-in [entity customization](https://www.home-assistant.io/docs/configuration/customizing-devices/) in `configuration.yaml`:

```yaml
homeassistant:
  customize:
    sensor.my_percentage_sensor:
      device_class: battery
  customize_glob:
    sensor.*humidity*:
      device_class: humidity
```

## Log Configuration
Use the following settings if you paste a log into a issue:

```yaml
logger:
  default: warning
  logs:
    homeassistant: warning
    homeassistant.helpers: warning
    custom_components.loxone: debug
    custom_components.loxone.api: debug
```

## Recorder Configuration
A Loxone system generates a few thousand events per day. These events are recorded in your homeassistant and the database file can grow a lot per day. It is recommended to exclude loxone events from the recorder using the following settings:

```yaml
recorder:
  exclude:
    event_types:
      - loxone_event
```

## Websocket direct command service
If you want to send data directly to Loxone inputs or blocks that are not (yet) supported, you can use this service to send a command:

```yaml
{
"uuid":"0f1e0b31-0179-7f77-ffff403fb0c34b9e",
"value":"pulse"
}
```
You can choose to send the commands using the UUID or the entity-name. See Developer Tools -> Services for more details.
Websocket direct commands enable you to, for example, send data captured by devices integrated in Home Assistant immediately to the miniserver using a VI on the miniserver.

## Some examples

### Using a TextInput to control a block's API Connector

The TextInput Virtual Input in the Miniserver enables some neat advanced applications.  
The Audioserver for example, has limited API-support. If you want to switch presets from Home Assistant, this is not possible using the traditional Audio Player API interface.

A neat way around this, is by adressing the Audio Player block's API Connector using a VTI (Virtual Text Input). This enables all of the block's functionality in Home Assistant.

First, create a VTI and connect it to the block's API Connector.

<img src="./images/vti.png" width=25%>

Second, send anything you want to this VTI from Home Assistant. In this use case, we want the Audio Player to switch to preset 4:

```
service: loxone.event_websocket_command
data:
  value: SET(Ap;Fav;4)
  device: text.ingang_vti1
```
You can even directly address the Audio Player's TTS engine.
```
service: loxone.event_websocket_command
data:
  device: text.ingang_vti1
  value: SET(AP;TTS;Woop-woop, that's the sound of da police)

```
### Using a Slider to send data from Home Assistant to the Loxone Miniserver

The Miniserver connects to/interfaces with a wide range of third party devices and services. However, support is quite limited in comparison to Home Assistant.  
If you take the DSMR P1 digital meter interface for example. This (serial) interface is supported on a wide range of platforms, but not on the Miniserver.  
A workaround could be creating a VI on the Miniserver and configuring it as a Slider. This VI will then appear in this integration as a Number entity to which you can send any numerical value.  
Any change in the sensor value in Home Assistant should trigger an automation that sets the new value to the entity in the Loxone integration.

## Advanced usage: what to do if your device is not supported
You can integrate nearly every Loxone Entity in your Home Assistant system by adding a custom sensor to your yaml file. 

### Example 1 with a RoomComfortTemperature
Here is a example of a sensor which is displaying the comfort temperature of a room controller v2:
```yaml
sensor:
  - name: RoomComfortTemperature
    platform: loxone
    uuidAction: "15beed5b-01ab-d81d-ffff2b06d5b9c660"
    unit_of_measurement: "°C"
    device_class: "temperature"    # Use device classes from homeassitant for example temperature, humidity, voltage   
    state_class: "total"           # measurement, total or total_increasing see https://developers.home-assistant.io/docs/core/entity/sensor/#long-term-statistics
```
In this example a sensor with the name roomcomforttemperature (sensor.roomcomforttemperature) is created. The sensor is listening to all events from the loxone system with the specified uuid ([How do you get the uuid?](#how-do-you-get-the-uuid)).

You can also send any websocket to a loxone entity for example to increase and decrease the temperature of a room controller v2. Here is a script that raises and lowers the temperature in 0.5 °C steps:

```yaml
script:
  tempup:
    alias: TempUp
    mode: single
    sequence:
    - data_template:
        uuid: "15beed5b-01ab-d81f-ffff403fb0c34b9e" 
        value: "setComfortTemperature/{{ states('sensor.roomcomforttemperature')|float+0.5}}"
      service: loxone.event_websocket_command
  tempdown:
    alias: TempDown
    mode: single
    sequence:
    - data_template:
        uuid: "15beed5b-01ab-d81f-ffff403fb0c34b9e"
        value: "setComfortTemperature/{{ states('sensor.roomcomforttemperature')|float-0.5}}"
      service: loxone.event_websocket_command
```

### Example 2 with a UpDownAnalog

- First get the uuidAction as described above for example. Let's assume your uuidAction for the UpDownAnalog is 152ecfaa-03ac-f715-ffff403fb0c34b9e.
- Create a Sensor do display the current value of the UpDownAnalog like this:
```yaml
sensor:
  - name: "Up and Down Sensor"
    platform: loxone
    uuidAction: "152ecfaa-03ac-f715-ffff403fb0c34b9e"
    unit_of_measurement: ""
```
- Create a script for incrementing up and down like this:
```yaml
down:
  alias: Down
  mode: single
  sequence:
  - data_template:
      uuid: "152ecfaa-03ac-f715-ffff403fb0c34b9e"
      value: "{{ states('sensor.up_and_down_sensor')|float-1}}"
    service: loxone.event_websocket_command

up:
  alias: Up
  mode: single
  sequence:
  - data_template:
      uuid: "152ecfaa-03ac-f715-ffff403fb0c34b9e"
      value: "{{ states('sensor.up_and_down_sensor')|float+1}}"
    service: loxone.event_websocket_command
```

The commands for each entity can be found in the structure file. You can download it from the [Loxone Homepage](https://www.loxone.com/dede/kb/api/).

## How do you get the uuid?

If you need the UUID of an entity to use it in a service call or to manually add it to Home Assistant, you can get it from your Loxone setup by visit the following site with your prefered browser:

```
http://{ip-address-of-your-loxone}:{port}/data/LoxAPP3.json

{ip-address-of-your-loxone} --> replace with the ip of your loxone 

{port} --> replace with your port (default: 80)
```
After entering your username and password you will see your LoxApp3.json. You can paste it in your prefered JSON editor/viewer (eg. https://jsonformatter.org/). 
In this file you can find all your uuid ids for all your devices.  


Here is a example of a Room Controller V2: 
```json
        "15beed5b-01ab-d81f-ffff403fb0c34b9e": {
            "name": "Intelligente Raumregelung",
            "type": "IRoomControllerV2",
            "uuidAction": "15beed5b-01ab-d81f-ffff403fb0c34b9e",
            "room": "13efd3e5-019d-8ad2-ffff403fb0c34b9e",
            "cat": "152c22de-0338-94b5-ffff403fb0c34b9e",
            "defaultRating": 2,
            "isFavorite": false,
            "isSecured": false,
            "details": {
                "timerModes": [
                    {
                        "name": "Anwesend",
                        "description": "Komfortbetrieb",
                        "id": 1
                    },
                    {
                        "name": "Abwesend",
                        "description": "Sparbetrieb",
                        "id": 0
                    },
                    {
                        "name": "Aus",
                        "description": "Geb\u00e4udeschutz",
                        "id": 2
                    }
                ],
                "format": "%.1f\u00b0",
                "connectedInputs": 0
            },
            "states": {
                "tempActual": "15beed5b-01ab-d7f7-ffff2b06d5b9c660",
                "tempTarget": "15beed5b-01ab-d81d-ffff2b06d5b9c660",
                "comfortTemperature": "15beed5b-01ab-d7ff-ffff2b06d5b9c660",
                "comfortTolerance": "15beed5b-01ab-d800-ffff2b06d5b9c660",
                "absentMinOffset": "15beed5b-01ab-d801-ffff2b06d5b9c660",
                "absentMaxOffset": "15beed5b-01ab-d802-ffff2b06d5b9c660",
                "frostProtectTemperature": "15beed5b-01ab-d803-ffff2b06d5b9c660",
                "heatProtectTemperature": "15beed5b-01ab-d804-ffff2b06d5b9c660",
                "activeMode": "15beed5b-01ab-d7f1-ffff2b06d5b9c660",
                "comfortTemperatureOffset": "15beed5b-01ab-d7ec-ffff2b06d5b9c660",
                "overrideEntries": "15beed5b-01ab-d7ed-ffff2b06d5b9c660",
                "prepareState": "15beed5b-01ab-d7ee-ffff2b06d5b9c660",
                "useOutdoor": "15beed5b-01ab-d7ef-ffff2b06d5b9c660",
                "operatingMode": "15beed5b-01ab-d7f2-ffff2b06d5b9c660",
                "overrideReason": "15beed5b-01ab-d7f4-ffff2b06d5b9c660",
                "openWindow": "15beed5b-01ab-d7f8-ffff2b06d5b9c660",
                "modeList": "15beed5b-01ab-d7f3-ffff2b06d5b9c660"
            },
            "subControls": {
                "15beed5b-01ab-d7eb-ffff2b06d5b9c660": {
                    "name": "Heating and Cooling",
                    "type": "IRCV2Daytimer",
                    "uuidAction": "15beed5b-01ab-d7eb-ffff2b06d5b9c660",
                    "defaultRating": 0,
                    "isFavorite": false,
                    "isSecured": false,
                    "details": {
                        "analog": true,
                        "format": "%.1f\u00b0"
                    },
                    "states": {
                        "entriesAndDefaultValue": "15beed5b-01ab-d7eb-ffff2b06d5b9c660",
                        "mode": "15beed5b-01ab-d81e-ffff2b06d5b9c660",
                        "modeList": "15beed5b-01ab-d7f3-ffff2b06d5b9c660",
                        "value": "15beed5b-01ab-d7f1-ffff2b06d5b9c660"
                    }
                }
            }
        },
```





