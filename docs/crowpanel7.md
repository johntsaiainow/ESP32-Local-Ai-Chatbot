# CrowPanel 7-inch + INMP441

<img src="media/boards/crowpanel7.jpg" width="480" alt="Elecrow CrowPanel 7-inch display">

*Product photo supplied by the project maintainer. The external INMP441 is not
shown; the dashboard on the display is product imagery, not the Osiris UI.*

Environment: `crowpanel7_inmp441`.

This experimental Osiris port targets the **basic Elecrow DIS08070H** with
ESP32-S3-WROOM-1-N4R8, 4 MB flash, 8 MB octal PSRAM, an 800×480 RGB display,
GT911 touch and the onboard NS4168 speaker amplifier. It does not target the
Advance AI models, P4 models or the 3.5-inch ESP Terminal with a camera.
No physical board has been flashed or tested during development of this port.

## Wiring

Use an INMP441 module with its left/right selection tied low:

| INMP441 / expansion-board signal | CrowPanel connection |
| --- | --- |
| VDD / microphone supply | **3.3 V**, regulated |
| GND | GND |
| SD / `MIC_DIN` (microphone output) | **GPIO38** (ESP32 input) |
| SCK / `MIC_SCK` | **GPIO42**, shared with the existing speaker bit clock |
| WS / `MIC_WS` | **GPIO18**, shared with the existing speaker word clock |
| L/R | GND (left slot); on the supplied schematic this is R1=0 Ω, R2=NC |
| RGB / LED data | **Not connected** |

GPIO17 remains the **speaker output**, not microphone data. GPIO37 is not
used by this driver; it belongs to octal PSRAM on N4R8. GPIO19/20 remain the
GT911 I2C bus. The driver does not repurpose these pins for microphone clocks.

These are **GPIO/net names, not connector pin positions**. The external GPIO_D
port does not, by itself, provide all microphone connections. Locate the
actual GPIO42/18 nets on the board or a verified breakout; tapping these nets
may require soldering. This port does not claim the pictured 8-pin expansion
board plugs directly into GPIO_D and I2C. Its H1-to-mainboard harness still
needs to be verified against the physical board revision.

Do not feed 5 V into INMP441 VDD. The supplied LED/microphone schematic uses a
shared VCC rail, so leaving only RGB data disconnected does not isolate LED
power. Verify that rail or separate the supplies before powering that board;
a standalone 3.3 V INMP441 module avoids that shared-rail issue.

Use the existing CrowPanel **SPK** connector and amplifier for playback.
SD mounting and RGB LED control are disabled in this target.

## Firmware behavior

- Audio uses standard Philips I2S at **16 kHz with two 32-bit slots** (64 bit
  clocks per frame), no MCLK. TX/RX share the same peripheral and clocks.
- The microphone's left-aligned 24-bit samples are reduced to signed PCM16.
  The application-facing stereo buffer duplicates the left microphone channel;
  the host protocol remains mono PCM16/16 kHz.
  Input has 4× software gain with saturation (no wraparound). If recordings clip
  or remain too quiet, set `-DOSIRIS_INMP441_GAIN=1` through `32` in this target's
  `build_flags`, rebuild, and compare recorded WAV levels.
- Speaker PCM16 samples are expanded into 32-bit slots. DMA auto-clear emits
  silence when the playback queue empties, while microphone clocks keep running.
  Capture and playback remain sequential; no echo cancellation is added.
- INMP441 has no configuration/identity registers. A successful microphone
  initialization log confirms the I2S driver, **not the presence of a microphone**.
- The 320×240 Osiris UI is scaled 2× into a centered 640×480 area with black
  side margins. Touch coordinates map back into that area. Settings, transport
  switching, cloud mode and the saved wake phrase are retained.
- RGB scanning uses the ESP-IDF LCD driver with a PSRAM framebuffer and two
  10-line **internal SRAM DMA bounce buffers** (32,000 bytes total). This replaces
  the legacy LovyanGFX RGB DMA/ISR path; LovyanGFX still renders fonts, emoji and
  touch. Default pixel clock is **12 MHz**, reduced from 15 MHz to ease memory
  contention. Changed row groups are redrawn instead of a full-screen scaled
  copy for every meter update. Unchanged frames are skipped.
  The RGB data pin table compensates for LovyanGFX's byte-swapped RGB565
  framebuffer, preserving emoji and text colors with the ESP-IDF driver.
  `-DOSIRIS_CROW_PCLK_HZ=15000000` can override the clock for a panel that needs
  the original timing, after verifying display stability on the real board.
- The driver probes PCA9557 at `0x18`. If present, it applies Elecrow's V3 touch
  reset/address-selection sequence. If absent, it uses the V2 initialization.
  GT911 reset/interrupt are not driven on GPIO38/15, which are already mic/LCD nets.
- Touch defaults to native orientation (`OSIRIS_CROW_TOUCH_ROTATION=0`), following
  the reported reversed-touch behavior with the previous 180-degree offset.
  If a different panel revision needs 180-degree compensation, add
  `-DOSIRIS_CROW_TOUCH_ROTATION=2` to this environment's `build_flags` and rebuild.
  Check the four corners and bottom Settings button on the real panel.
- BOOT/GPIO0 is the running RGB pixel clock. Settings uses touch, not a GPIO0
  long-press handler. Startup opens the setup AP if Wi-Fi cannot connect.

The setup AP is `CrowPanel7-Setup-XXXX`, password `box3setup`, portal
`192.168.4.1`. Configure Wi-Fi and the provider/wake phrase through **Setup**.

## Build and flash

```bash
pio run -e crowpanel7_inmp441
pio run -e crowpanel7_inmp441 --target upload --upload-port /dev/ttyUSB0
pio device monitor -e crowpanel7_inmp441 --port /dev/ttyUSB0 --baud 115200
```

This board uses its **CH340 USB-to-UART bridge**, not native USB CDC. Native
USB shares GPIO19/20 with touch and is disabled. Prefer **Wi-Fi TCP:8233** for
host audio: UART at 115200 baud cannot sustain real-time 16 kHz PCM16 over the
hex-encoded BOX1 protocol. USB-UART remains useful for flashing, diagnostics
and control; standalone cloud mode uses Wi-Fi directly.

The custom `partitions/osiris_4MB.csv` has a single 3.75 MB application slot,
NVS and coredump storage, with **no second OTA slot or filesystem partition**.
PlatformIO upload installs the matching bootloader, partition table and app.
The application-only `firmware.bin` belongs at **0x10000**; the combined
`firmware.factory.bin` belongs at **0x0**. Back up existing firmware and any
filesystem contents needed for restoration before changing partition layouts.

## Verification

The CrowPanel target and the four existing board targets compile successfully.
The 98 host regression tests and portable audio conversion/gain checks pass.

The port needs physical verification of RGB display stability during network
traffic, touch orientation/reset on the actual revision, microphone wiring and
gain, and speaker format/volume. Start with a recorded WAV and moderate-volume
playback before a complete cloud conversation. Check the WAV's pitch and timing
and confirm that Settings and USB/Wi-Fi switching remain usable.

For flicker testing, compare an idle screen, active microphone meter, Wi-Fi
connection/traffic and speaker playback. The boot log should show
`CrowPanel RGB: ESP-IDF DMA` and the SRAM bounce buffers. The DMA/partial-update
revision compiles successfully; its effect on the reported severe flicker still
needs verification on the physical panel. It preserves the native touch offset.

The portable sample conversion test checks polarity, bit alignment and every
PCM16 value, including negative full-scale without signed-shift overflow:

```bash
g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=undefined tests/test_i2s_pcm.cpp -o /tmp/osiris-i2s-pcm
/tmp/osiris-i2s-pcm
```

## References

- [Elecrow pinout, RGB timings and V2/V3 touch notes](https://media-cdn.elecrow.com/wiki/esp32-display-702727-intelligent-touch-screen-wi-fi26ble-800480-hmi-display.html)
- [Official board repository](https://github.com/Elecrow-RD/CrowPanel-7.0-HMI-ESP32-Display-800x480)
- [Official V3 speaker example](https://github.com/Elecrow-RD/CrowPanel-7.0-HMI-ESP32-Display-800x480/blob/master/example/V3.0/Arduino/Course/Example2_Play_music/Example2_Play_music.ino)
- [Espressif octal PSRAM pin assignments](https://documentation.espressif.com/esp-hardware-design-guidelines/en/latest/esp32s3/index.html)
- [Espressif RGB bounce-buffer and bandwidth guidance](https://docs.espressif.com/projects/esp-idf/en/v5.4.2/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html)
