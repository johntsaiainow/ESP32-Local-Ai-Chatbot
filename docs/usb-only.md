# USB-only firmware (Wi-Fi disabled)

Run `python3 configure.py` and set **Wi-Fi (firmware)** to **OFF - USB only**.
Choose **Build and upload** to apply it. **Save configuration** saves the selection
for the next build without changing the device currently running.

For scripts:

```bash
python3 configure.py --wifi off --save
python3 configure.py --env esp32s3box3 --wifi off --action upload
```

Use the actual board and upload port. To restore Wi-Fi, select ON and rebuild /
flash, or use `--wifi on --action upload`. Existing configuration files without a
Wi-Fi option retain the previous behavior (Wi-Fi ON). Direct PlatformIO builds
read the saved selection; `OSIRIS_WIFI_ENABLED=off pio run` overrides it for one
build. `--dry-run` previews the selection without saving or flashing.

With Wi-Fi OFF:

- The station radio is kept off and automatic reconnection is disabled. Firmware
  does not join Wi-Fi, start a TCP server or open the setup hotspot.
- The firmware uses host mode over USB even if standalone cloud mode was saved
  previously. Saved Wi-Fi/cloud credentials and the wake phrase are preserved.
- Settings and transport-switch controls are disabled. The footer says
  `WiFi OFF - USB only`.
- The repeater is forced off, including when custom build flags request it.
  Its saved preference is preserved and becomes available again with Wi-Fi ON.

Start the host with an explicit USB port, which also overrides a saved host
network endpoint in the environment:

```bash
host/.venv/bin/python host/voice_agent.py --port /dev/ttyACM0 --language auto
```

This disables Wi-Fi on the chatbot ESP32. The computer can still use cloud
providers or receive RuView MQTT events through its own network connection.
RuView sensing continues to require its separate Wi-Fi sensor/server. For fully
offline operation, also select local host speech and model backends.

No device flashing or radio measurement is performed by selecting/saving OFF.
Build verification does not establish physical USB audio or RF performance.

Validation: BOX-3 builds passed for Wi-Fi OFF (with repeater requested ON, forced
OFF) and Wi-Fi ON with repeater ON. The USB-only image includes its disabled
status and excludes the station/repeater startup markers. Configuration, wake
gating, presence, reconnect and USB/TCP transport regression tests passed. No
firmware was flashed and physical radio-off behavior remains unmeasured.
