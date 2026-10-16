# ESP32 Local AI Chatbot

**An ESP32-S3-BOX-3 voice and display terminal for a locally hosted AI coding agent.**

Turn an ESP32-S3-BOX-3 into a compact conversational interface with multilingual text, color emoji expressions, microphone input, speaker output, and USB or Wi-Fi connectivity to a Linux or macOS host. Speech recognition and synthesis run on the host rather than on the ESP32.

> **Architecture note:** “Local AI” refers to the host-side voice pipeline and agent integration. The ESP32 handles display, audio capture/playback, and transport; it does not run the language model itself. The Pi agent's inference backend depends on your Pi configuration and may be local or remote.

## Features

- **ESP32-S3-BOX-3 interface:** built-in display, microphone, speaker, and audio-level meter.
- **Multilingual display:** English, Simplified Chinese, Traditional Chinese, Japanese, and Korean using bundled 16-pixel LovyanGFX efonts.
- **Color emoji avatar:** LovyanGFX-rendered Noto emoji with a supported subset of inline icons and 13 state expressions, including sleeping while waiting for the wake phrase.
- **USB or Wi-Fi transport:** display text, capture microphone audio, and play host-generated PCM audio; show the active transport and switch without losing the Pi session.
- **Osiris wake phrase:** say “Osiris!” before a spoken request, with a 15-second follow-up window and sleeping/listening emoji feedback.
- **WiFi Manager:** saved Wi-Fi credentials, automatic setup hotspot on startup connection failure, and an on-screen Settings button.
- **Offline speech processing:** faster-whisper for speech-to-text, OpenCC for Traditional Chinese conversion, and Piper for text-to-speech.
- **Pi coding-agent integration:** optional Pi extension tools and a standalone conversational voice agent.
- **Local music playback:** decode files from a local music directory with mpv and stream them to the BOX-3 speaker.
- **Robust audio transport:** offset and CRC32 validation, retries, synchronization, and PSRAM-buffered continuous playback on compatible firmware.
- **Linux-first workflow:** PlatformIO, Python virtual environments, and terminal-based diagnostics.

## System architecture

```text
ESP32-S3-BOX-3                    Linux / macOS host
┌─────────────────────┐          ┌─────────────────────────────┐
│ Microphone + I2S    │ ───────▶ │ host/box3.py               │
│ LCD + color emoji  │ ◀─────── │ host/voice_agent.py         │
│ Speaker + I2S      │ ◀─────── │ STT → wake gate → Pi → TTS │
└─────────────────────┘          │ Local music (mpv/ffmpeg)   │
          USB or Wi-Fi TCP:8233   └─────────────────────────────┘
```

The device captures audio and displays responses; the host performs recognition, agent execution, speech generation, and optional music decoding. Recording and playback are sequential; this is not a full-duplex echo-canceling voice system.

## Hardware and software

| Component | Requirement |
| --- | --- |
| Device | ESP32-S3-BOX-3 |
| Firmware | Arduino framework via PlatformIO / pioarduino |
| Display library | LovyanGFX |
| Host | Linux or macOS (POSIX serial access) |
| Connection | Native USB data cable, or Wi-Fi LAN with TCP port 8233 reachable |
| Power | USB power is still required during Wi-Fi operation |
| Host runtime | Python 3, virtual environment, Pi CLI for agent features |
| Speech | faster-whisper, OpenCC, Piper voice models |
| Music | mpv; ffmpeg alternative |
| Audio format | 16 kHz, mono, signed 16-bit PCM WAV |

The firmware is configured for the board's **16 MB flash partition layout** to accommodate bundled fonts. Flashing a new partition table may make existing filesystem contents incompatible.

## Repository layout

```text
ESP32-Local-Ai-Chatbot/
├── src/                  # ESP32 firmware and selected emoji assets
├── host/                 # USB/TCP client, speech adapters, voice agent
│   ├── README.md         # Detailed host setup and protocol reference
│   ├── box3.py           # Host-side device control
│   ├── voice_agent.py    # Standalone voice conversation loop
│   └── offline_speech.py # Speech recognition and synthesis CLI
├── pi/                   # Pi coding-agent extension
│   └── box3.ts
├── tests/                # Host, protocol, wake-word, and TCP tests
├── third_party/          # Emoji attribution and upstream licenses
├── platformio.ini        # ESP32-S3-BOX-3 build configuration
└── README.md
```

## Quick start

### 1. Clone and build firmware

Install [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html), then:

```bash
git clone https://github.com/johntsaiainow/ESP32-Local-Ai-Chatbot.git
cd ESP32-Local-Ai-Chatbot
pio run
pio run --target upload
```

To inspect boot and hardware diagnostics:

```bash
pio device monitor --baud 115200
```

**Close the serial monitor before starting the host bridge.** Only one application should own the USB serial port at a time.

### 2. Set up the host bridge

```bash
python3 -m venv host/.venv
host/.venv/bin/pip install -r host/requirements.txt
export BOX3_PYTHON="$PWD/host/.venv/bin/python"
export BOX3_PORT=/dev/ttyACM0
```

Change `BOX3_PORT` to the actual device path. To discover ports:

```bash
"$BOX3_PYTHON" -m serial.tools.list_ports
```

Check device status, render text, and test audio:

```bash
"$BOX3_PYTHON" host/box3.py status
"$BOX3_PYTHON" host/box3.py display --language en -- 'Pi is ready!'
"$BOX3_PYTHON" host/box3.py display --language zh -- '你好 🤖 ✅'
"$BOX3_PYTHON" host/box3.py record /tmp/box3-mic.wav --seconds 5
"$BOX3_PYTHON" host/box3.py play /tmp/box3-mic.wav
"$BOX3_PYTHON" host/box3.py speaker-test
```

The speaker test generates a one-second 440 Hz tone. A codec-ready status alone does not prove the physical speaker or microphone works; verify with real recording and playback.

### 3. Enable offline speech

Install the additional Python dependencies and system audio utilities:

```bash
sudo apt install ffmpeg mpv
"$BOX3_PYTHON" -m pip install -r host/requirements-offline.txt
```

The default faster-whisper multilingual model is downloaded on first use and cached for later offline recognition. **Piper ONNX voices and their matching `.onnx.json` files must be installed separately**; voice models are not bundled with this repository. The host guide documents the default voice locations and environment overrides.

After configuring Pi CLI and the Piper voices, start the standalone agent:

```bash
"$BOX3_PYTHON" host/voice_agent.py --language auto
```

Useful alternatives:

```bash
"$BOX3_PYTHON" host/voice_agent.py --language zh
"$BOX3_PYTHON" host/voice_agent.py --language zh --silence 1.5
"$BOX3_PYTHON" host/voice_agent.py --keyboard-only
```

`--language auto` supports English/Chinese recognition and mixed utterances. The device-side capture mode uses an amplitude threshold and silence detection, not a neural VAD model. Type `/quit` to exit the voice agent.

### 4. Configure Wi-Fi and transport switching

For USB operation, keep using `BOX3_PORT` from step 2. Wi-Fi setup is optional.

#### Wi-Fi setup / Setting Mode

Tap **Settings** at the bottom right of the touchscreen to enter Setting Mode.
Connect a phone or computer to the **BOX3-Setup-XXXX** hotspot shown on the
display (password: **box3setup**), then open **http://192.168.4.1** if the
configuration page does not appear automatically. Select your Wi-Fi network,
enter its password, and save. Credentials are stored on the device and reused
after restart; no source-code credentials are required.

At startup the device tries the saved network for 15 seconds before opening
the setup hotspot. Successful configuration closes the portal. Tap **Exit**
to close it manually; it also times out after 3 minutes. Settings can reopen
the portal without erasing the saved network. The footer shows the station IP
when connected, or the setup hotspot and password while configuring.

The portal uses [WiFiManager](https://github.com/tzapu/WiFiManager).
Settings input and portal processing may be delayed during synchronous
recording/playback commands or a Wi-Fi connection attempt.

#### Connect Pi Coding Agent over Wi-Fi

Flash the updated firmware first. Connect BOX-3 and the computer running Pi CLI
to the same LAN, then use the BOX-3 IP shown in the display footer:

```bash
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --language auto
```

Replace the example IP with your device's IP. The host connects to BOX-3 TCP
port **8233**; the existing speech recognition, Pi CLI conversation session,
reply display, speech synthesis, and music playback work over this connection.
The computer still needs the host speech dependencies, voice models, and Pi CLI
setup described below. BOX-3 only needs USB power during Wi-Fi operation.

Alternatively, set `BOX3_HOST=192.168.1.50`. Explicit `--host` or `--port`
overrides environment defaults; `BOX3_HOST` takes precedence over `BOX3_PORT`.
Use `--port /dev/ttyACM0` to select USB explicitly. Diagnostic commands also
accept `--port socket://192.168.1.50:8233`, for example:

```bash
host/.venv/bin/python host/box3.py --port socket://192.168.1.50:8233 status
host/.venv/bin/python host/box3.py --port socket://192.168.1.50:8233 speaker-test
```

To enable switching during the same Pi conversation, supply both endpoints:

```bash
host/.venv/bin/python host/voice_agent.py --port /dev/ttyACM0 --host 192.168.1.50 --transport wifi
```

The display footer shows **Via: USB** or **Via: WiFi**, independently of Wi-Fi
network connection status. When both endpoints are configured and Wi-Fi is
connected, tap **Switch** beside Settings. A pending indicator remains until
the host switches at the next completed conversation/recording/playback boundary.
You can also type `/transport usb`, `/transport wifi`, or `/transport status` in
the host terminal. Only the selected transport is opened at a time. The Pi session
is preserved, and a failed switch attempts to restore the previous connection.
Both endpoints must refer to the same BOX-3. Switching requires updated firmware
advertising `link=1`; a single endpoint remains compatible with older firmware.
An endpoint being configured does not guarantee that its cable/network is reachable.
With no `--transport`, an explicit `--host` selects Wi-Fi, an explicit `--port`
selects that port, and environment defaults prefer `BOX3_HOST` over `BOX3_PORT`.

One TCP controller owns the device while connected; competing TCP clients are
rejected and USB commands are discarded during that connection. Disconnecting
releases audio buffers and restores USB control. If a connection fails, restart
the host command after connectivity returns. The TCP protocol has no authentication
or encryption and is intended for a trusted local network; do not expose port
8233 to the internet.

### 5. Optional Pi extension

For direct Pi tool access instead of the standalone voice-agent loop:

```bash
pi -e ./pi/box3.ts
```

The extension exposes:

| Tool | Purpose |
| --- | --- |
| `box3_display` | Show multilingual text and supported emoji |
| `box3_say` | Synthesize speech on the host and play through BOX-3 |
| `box3_listen` | Capture and transcribe an English or Chinese utterance |

Within Pi, `/box-listen en` or `/box-listen zh` records an utterance and submits the transcript. The standalone voice agent and Pi USB extension **must not access the same serial port simultaneously**.

## Wake phrase: Osiris!

Spoken requests now require **Osiris** by default over USB or Wi-Fi:

- Say **“Osiris, what is the weather?”** in one utterance, or
- Say **“Osiris!”**, wait for **Awake!** on the display, then speak one request
  within **15 seconds**.

After each completed answer, the agent stays awake for **30 seconds** so you
can ask a follow-up without repeating “Osiris!”. Each completed reply starts a
fresh 30-second window. If the window expires, the sleeping emoji returns and
the wake phrase is required again. The standalone wake still allows 15 seconds
for the first request. Unrelated speech is ignored while asleep. Keyboard prompts and `/transport` commands do not need a wake phrase.
The spelling is **Osiris**; matching ignores case and does not require the
exclamation mark.

```bash
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --language auto
# Optional: change initial/follow-up timeouts, keyword, or disable wake gating
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --followup-timeout 30
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --wake-timeout 20
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --wake-word 'Hey Osiris'
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --no-wake-word
```

Wake detection uses the existing host speech-to-text transcript, rather than a
separate trained keyword model. Audio still travels to the host and is recognized
while waiting; requests only go to Pi after the wake phrase matches. Recognition
accuracy and wake response time depend on the speech model and language setting;
`--language auto` allows the English wake phrase with Chinese or English requests.
It listens between requests, and remains paused during Pi processing and speaker
playback. This change only requires restarting the updated host script; no new
firmware is needed for wake gating.

## Multilingual display and emoji

Firmware provides `printLocalizedText(x, y, text, language)` with the following language options:

- `English`
- `SimplifiedChinese`
- `TraditionalChinese`
- `Japanese`
- `Korean`

Example:

```cpp
printLocalizedText(10, 100, "\uC548\uB155\uD558\uC138\uC694",
                   DisplayLanguage::Korean);
printLocalizedText(10, 10, "Agent ready \U0001F916 \u2705",
                   DisplayLanguage::English);
```

Supported inline icons use 16×16 color PNGs from LGFX_Fonts: selected faces, ear, robot, microphone, speaker, check, cross, warning, and heart symbols. This is **not a complete Unicode emoji font**. Unsupported glyphs and complex emoji sequences may not render. Mixed-language strings do not receive automatic font fallback.

The Osiris avatar uses 64×64 Noto color emoji from
[LGFX_Fonts](https://github.com/tobozo/LGFX_Fonts), the asset package used by
LovyanGFX's emoji example. Existing `FACE` commands select the expression:

| State | Emoji |
| --- | --- |
| `happy` | 😀 |
| `listening` | 👂 |
| `thinking` | 🤔 |
| `speaking` | 😃 |
| `music` | 😎 |
| `sad` | 😢 |
| `error` | 😵 |
| `sleeping` | 😴 |
| `waiting` | ⌛ |
| `surprised` | 😮 |
| `love` | 🥰 |
| `success` | 🎉 |
| `warning` | ⚠️ |

While waiting for “Osiris!”, the voice agent automatically selects `sleeping`;
after waking, it selects `listening`. The sleeping, waiting, surprised, love, success, and warning emoji are also available
inline at 16×16. Updated firmware advertises `emojistates=1`; the Python client
falls back to the original expressions when connected to older firmware.

Expressions redraw when host state changes; they are static images rather than
lip-synced animations. Only selected original PNG assets are embedded, so no SD
card or additional font runtime is required. Attribution and upstream licenses
are in [third_party/lgfx_emojis](third_party/lgfx_emojis/).

## Audio transport

The host and firmware use the same line-oriented `BOX1` requests and acknowledgements over native USB or Wi-Fi TCP. The protocol supports display messages, microphone capture, playback, and cancellation. Current firmware adds checked audio chunks with offsets/CRC32, retry handling, and streaming synchronization.

| Capability | Notes |
| --- | --- |
| Recording | 16 kHz mono PCM16, maximum 10 seconds per captured utterance |
| Playback | 16 kHz mono PCM16 |
| Checked transfers | Chunk offsets and CRC32 integrity checks |
| Streaming | PSRAM ring buffer on supported firmware |
| Wi-Fi playback | Up to 8192 PCM bytes per checked packet; 500 ms audio prefill |
| Wi-Fi recording downloads | Up to 4096 PCM bytes per read |
| USB playback | Existing packet sizes and two-second prefill |
| Transport selection | Touchscreen Switch or `/transport usb`, `/transport wifi` |
| Playback diagnostics | `underruns` and `stalled_ms` report queued-audio starvation |
| Microphone | Paused during speaker playback |
| Concurrency | One host operation at a time |

Wi-Fi uses batched TCP reads on the host and device, TCP_NODELAY, and disabled
ESP32 Wi-Fi power saving to reduce transport stalls. CRC validation, retries,
and stream backpressure remain enabled. Update both firmware and host code to
use these optimizations. Larger transfer sizes are negotiated through
`netchunk=8192` and `netread=4096`; USB retains its existing transfer sizes.

At playback completion the terminal prints, for example:

```text
Audio supply: underruns=0, stalled_ms=0
```

Nonzero values mean the playback worker ran out of queued audio. They measure
audio supply stalls, rather than speech recognition, Pi response, or synthesis
time. The prefill values describe buffered audio duration, not a guarantee of
end-to-end response latency.

For wire commands, version compatibility, status flags (`audio=pull1`, `vad=1`,
`stream=ring1`, `streamrev=4`, `link=1`, `emojistates=1`), and recovery procedures, see [host/README.md](host/README.md).

## Local music

The standalone voice agent can play files from `~/Music` (or a directory selected with `--music-dir`). Spoken song requests are matched against local filenames, decoded with mpv, and streamed to the BOX-3. It does not search online music services or control a separate host-speaker jukebox process.

For an explicit local track, use the agent command:

```text
/music /path/to/song.mp3
```

After playback, the agent stays awake for 30 seconds for a follow-up, then returns to waiting for “Osiris!”. Transport stalls may still cause audible gaps.

## Testing and diagnostics

```bash
# Python tests (USB/TCP protocol, switching, wake gating, and speech adapters)
host/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'

# Host-side UTF-8 decoder test
g++ -std=c++17 tests/test_utf8.cpp -o /tmp/box3-test-utf8
/tmp/box3-test-utf8

# Firmware compilation
pio run

# Real-device validation
"$BOX3_PYTHON" host/box3.py status
"$BOX3_PYTHON" host/box3.py record /tmp/box3-check.wav --seconds 1
"$BOX3_PYTHON" host/box3.py speaker-test
```

Automated tests and successful compilation do not substitute for hardware verification of the microphone, speaker, display, wake recognition, and USB/Wi-Fi links.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Serial port busy | Close PlatformIO monitor, the voice agent, or another bridge client |
| Device not found | Verify native USB data cable, port path, and serial permissions |
| No microphone audio | Inspect device status, I2S initialization, and a saved test WAV |
| No speaker sound | Run `speaker-test`; codec initialization alone is insufficient |
| Corrupted audio / malformed response | Reflash matching firmware, close other serial clients, and retry |
| Wi-Fi connection fails | Confirm the footer IP, same LAN, reachable TCP port 8233, and no other controller |
| Switch button missing | Provide both `--port` and `--host`, connect Wi-Fi, and flash firmware with `link=1` |
| Playback interruptions | Update host and firmware; check `Audio supply` counters and USB/Wi-Fi transfer health |
| Wake phrase ignored | Say “Osiris!”, wait for Awake!, use `--language auto`; try `--no-wake-word` to isolate recognition |
| Sleeping emoji missing | Restart the updated voice agent and flash firmware with `emojistates=1` |
| Missing Chinese/Japanese/Korean glyphs | Select the correct display language and check bundled font coverage |
| Speech model missing | Install matching Piper `.onnx` / `.onnx.json` files and confirm model paths |

## Documentation

- [Host setup, offline voice agent, and USB/TCP protocol](host/README.md)
- [PlatformIO configuration](platformio.ini)
- [Firmware source](src/)
- [Pi extension](pi/box3.ts)
- [Tests](tests/)
- [Emoji asset attribution and licenses](third_party/lgfx_emojis/)

## Project scope

This is a **host-assisted local voice terminal**, not an on-device ESP32 language model. Speech recognition and synthesis can run offline after their models are installed. Pi agent capabilities, tool access, and whether inference requires a network depend on the host configuration. The project does not currently provide full-duplex voice, acoustic echo cancellation, unrestricted emoji rendering, or cloud music search.

## License

No project-wide license is declared here. Bundled Noto emoji assets retain their SIL Open Font License 1.1 and upstream notices in [third_party/lgfx_emojis](third_party/lgfx_emojis/). Those licenses do not establish a license for the rest of this repository.
