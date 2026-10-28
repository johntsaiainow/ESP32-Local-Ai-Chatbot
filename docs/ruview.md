# RuView presence wake

Osiris host-assisted voice mode can open its normal request window when RuView
reports an arrival. The display changes from sleeping to listening; speak your
request directly without saying “Osiris”. No greeting or LLM request is generated
by presence alone. After the reply, the normal follow-up window applies.

This integration requires a separate RuView CSI sensor node, a running RuView
sensing server using real ESP32 input, and an MQTT broker reachable by both the
server and the Osiris host. Home Assistant is not required. It does not flash
RuView onto the chatbot board or add CSI capture to Osiris firmware. Desktop and
standalone cloud modes are not connected to this adapter.

## Enable or disable with configure.py

Run `python3 configure.py`. Set **RuView presence wake (host)** to ON or OFF
using Left/Right or Enter. Open **RuView MQTT settings** to enter the broker
hostname and exact presence state topic, then choose **Save configuration**.
RuView defaults to OFF. The selection and connection settings are saved locally
in `.build-menu.json`; restart `host/voice_agent.py` to apply them. Firmware
rebuilding/flashing is not required for this host feature.

For scripts, save without building:

```bash
python3 configure.py --ruview on --ruview-mqtt-host 192.168.1.10 \
  --ruview-presence-topic 'REPLACE_WITH_DISCOVERED_STATE_TOPIC' --save
python3 configure.py --ruview off --save
```

After saving ON and installing the optional dependency, launch the host agent
normally. It reads the saved broker and topic. Missing settings produce a startup
error. Authentication, TLS, port and custom payloads remain host CLI options.
`voice_agent.py --no-ruview` disables the feature for one run; `--ruview` enables
it using the saved connection settings. Explicit MQTT host/topic flags also
opt into RuView for that run. OFF preserves connection settings for later reuse.

## Setup

1. Set up and calibrate the sensor using the
   [RuView upstream guide](https://github.com/ruvnet/RuView).
2. Enable the server's MQTT publisher with `--source esp32 --mqtt --mqtt-host BROKER`.
   Build/version details and authentication options are in the
   [upstream MQTT guide](https://github.com/ruvnet/RuView/blob/main/docs/integrations/home-assistant.md).
3. Inspect MQTT discovery using `mosquitto_sub -h BROKER -t 'homeassistant/#' -v`.
   Find the selected node's **presence** binary sensor config. Copy its exact
   `state_topic`, `payload_on`, and `payload_off`. Use presence, not room_active
   or a discovery/config topic. Confirm that walking in/out changes live state.
4. Install the optional client dependency and start Osiris:

```bash
host/.venv/bin/python -m pip install -r host/requirements-ruview.txt
host/.venv/bin/python host/voice_agent.py \
  --port /dev/ttyACM0 --language auto \
  --ruview-mqtt-host 192.168.1.10 \
  --ruview-presence-topic 'REPLACE_WITH_DISCOVERED_STATE_TOPIC' \
  --ruview-on-payload ON --ruview-off-payload OFF
```

Replace the example broker, serial port, topic and payloads with your values.
Existing host speech/backend setup is still required; `--host BOX_IP` can replace
the serial port. For authentication, pass `--ruview-mqtt-username USER` and put
the password in `MQTT_PASSWORD` (or select another variable with
`--ruview-mqtt-password-env`). Use `--ruview-mqtt-tls --ruview-mqtt-port 8883`
for TLS with the system CA trust store.

## Behavior and limits

- A fresh, non-retained ON opens a `--wake-timeout` window (default 15 seconds).
  Continuous ON heartbeats do not reopen or extend it. Voice wake remains usable.
- OFF followed by ON at least five seconds later rearms the arrival trigger.
  Brief OFF/ON flicker is ignored. OFF cancels a pending wake, but does not
  interrupt a request or close an already open speech window.
- Retained broker messages never wake the assistant. On startup, someone already
  present can trigger on the first live ON heartbeat. Reconnection preserves
  occupancy so a connection drop alone does not trigger another wake.
- Pending arrivals expire after ten seconds, to avoid delayed wakes following
  long replies. Arrivals during an existing listening window are consumed.
- MQTT runs in the background; device operations remain in the voice loop.
  Screen changes can wait for the current blocking recording/STT operation.
  A fresh event during recording can also authorize that recording's request.
- Without MQTT input the existing voice wake behavior continues. Presence wake
  cannot be combined with `--keyboard-only` or `--no-wake-word`.
- “Sleeping” is the existing avatar/wake-gate state, not hardware deep sleep or
  a disabled microphone. Presence sensing can authorize background speech as a
  request during the open window; tune sensor placement accordingly.

Validation: automated tests cover arrival gating, absence hysteresis, retained
and expired events, disconnects, payload filtering and preservation of existing
listening deadlines. Real CSI sensing, broker interoperability and physical
wake latency have not yet been validated on hardware.
