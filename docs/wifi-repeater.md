# Optional Wi-Fi repeater

`configure.py` can compile Osiris with an IPv4 NAT repeater. The ESP32 joins the
saved upstream Wi-Fi and offers a separate password-protected Wi-Fi network for
up to four clients. This is a routed AP+STA network with NAT, not a transparent
bridge or mesh extender. It is independent of the host-side RuView switch.

## Enable or disable

```bash
python3 configure.py
```

Set **Wi-Fi repeater (firmware)** to **ON** or **OFF** using Left/Right or Enter.
Choose **Build and upload** to apply it. The default is OFF. The **Wi-Fi (firmware)** switch must be ON; Wi-Fi OFF
forces repeater OFF regardless of its saved preference. See [USB-only mode](usb-only.md). **Save configuration**
only saves the next build's selection; it does not change running firmware.

For scripts:

```bash
python3 configure.py --env esp32s3box3 --wifi-repeater on --action upload
python3 configure.py --env esp32s3box3 --wifi-repeater off --action upload
```

Select the actual board environment and upload port as needed. To preview without
saving, building or flashing:

```bash
python3 configure.py --wifi-repeater on --dry-run
```

Direct `pio run` reads the same saved setting. Override it for one build with
`OSIRIS_WIFI_REPEATER=on pio run` or `OSIRIS_WIFI_REPEATER=off pio run`.

## Connect a client

Configure upstream Wi-Fi using the normal Osiris Settings portal first. When the
station has an IP address and the portal is closed, the repeater starts:

- SSID: `Osiris-Repeater-XXXXXX` (last three bytes of the station MAC).
- Password: a random 24-character value generated on the device and stored in
  its own NVS namespace. Reboots and ON/OFF firmware changes preserve it; erasing
  NVS generates a new value.
- Read the SSID, AP address and password in the local serial monitor:
  `pio device monitor --baud 115200`. Close the monitor before running the host
  voice agent. Credentials are printed when the repeater starts.
- The footer shows `RP:on` while the repeater is active.

The AP normally uses `192.168.50.1/24`. If that overlaps the upstream subnet, it
tries `172.31.254.1/24`, then `10.254.254.1/24`; if all overlap it stays off and
logs the reason. DHCP supplies the upstream DNS server (or `1.1.1.1` if none was
provided). Clients share the ESP32's upstream IPv4 connection through NAPT.

## Interaction and validation

Opening Settings stops the repeater and disconnects its clients so WiFiManager
can use its normal setup AP at `192.168.4.1`. Closing Settings restarts the
repeater once upstream Wi-Fi is ready. Upstream disconnection stops it; reconnect
restarts it. Startup failures retry at ten-second intervals. A changed upstream
IP or DNS restarts the repeater so clients receive fresh network settings.

Both interfaces share the ESP32's radio and upstream channel. Repeater traffic
shares resources with speech and model traffic; throughput, audio latency,
DNS behavior, reconnects and portal transitions require physical validation.
Multicast discovery across the NAT boundary is not provided. This option does
not supply RuView CSI sensing firmware or guarantee CSI UDP auto-discovery across
subnets; keep the sensing node and server on a directly reachable network.

The pinned Arduino SDK includes IPv4 forwarding and NAPT for ESP32-S3. Builds with
an SDK lacking those capabilities fail explicitly when the option is ON. OFF
compiles out the repeater implementation and its NVS credential handling.

Validation: BOX-3 firmware builds passed with the option ON and OFF; the OFF
image excludes the repeater startup marker. Configuration tests and the
existing Wi-Fi recovery C++ test passed. No firmware was uploaded and no physical
repeater connectivity or performance testing has been performed.
