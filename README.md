# ESP32 Local AI Chatbot

**An ESP32-S3-BOX-3 voice and display terminal for a locally hosted AI coding agent.**

Turn an ESP32-S3-BOX-3 into a compact conversational interface with multilingual text, expressive robot faces, microphone input, speaker output, and USB or Wi-Fi connectivity to a Linux or macOS host. Speech recognition and synthesis run on the host rather than on the ESP32.

> **Architecture note:** “Local AI” refers to the host-side voice pipeline and agent integration. The ESP32 handles display, audio capture/playback, and transport; it does not run the language model itself. The Pi agent's inference backend depends on your Pi configuration and may be local or remote.

## Features

- **ESP32-S3-BOX-3 interface:** built-in display, microphone, speaker, and audio-level meter.
- **Multilingual display:** English, Simplified Chinese, Traditional Chinese, Japanese, and Korean using bundled 16-pixel LovyanGFX efonts.
- **Emoji and robot avatar:** a supported subset of colorful inline icons and static expressions for listening, thinking, speaking, music, and error states.
- **Native USB bridge:** display text, record microphone audio, and play host-generated PCM audio.
- **WiFi Manager:** saved Wi-Fi credentials, automatic setup hotspot on startup connection failure, and an on-screen Settings button.
- **Offline speech processing:** faster-whisper for speech-to-text, OpenCC for Traditional Chinese conversion, and Piper for text-to-speech.
- **Pi coding-agent integration:** optional Pi extension tools and a standalone conversational voice agent.
- **Local music playback:** decode files from a local music directory with mpv and stream them to the BOX-3 speaker.
- **Robust audio transport:** offset and CRC32 validation, retries, synchronization, and PSRAM-buffered continuous playback on compatible firmware.
- **Linux-first workflow:** PlatformIO, Python virtual environments, and terminal-based diagnostics.

## System architecture

```text
  ESP32-S3-BOX-3                         Linux / macOS host
┌────────────────────────┐   USB    ┌──────────────────────────────┐
│ Microphone / I2S codec │─────────▶│ USB bridge (host/box3.py)    │
│ LCD + multilingual UI  │◀─────────│                              │
│ Robot face + level VU  │          │ faster-whisper → OpenCC      │
│ Speaker / I2S codec    │◀─────────│ Pi coding agent → Piper      │
└────────────────────────┘          │ Local music (mpv)            │
                                    └──────────────────────────────┘
```

The device captures audio and displays responses; the host performs recognition, agent execution, speech generation, and optional music decoding. Recording and playback are sequential; this is not a full-duplex echo-canceling voice system.

## Hardware and software

| Component | Requirement |
| --- | --- |
| Device | ESP32-S3-BOX-3 |
| Firmware | Arduino framework via PlatformIO / pioarduino |
| Display library | LovyanGFX |
| Host | Linux or macOS (POSIX serial access) |
| USB | Native USB data connection |
| Host runtime | Python 3, virtual environment, Pi CLI for agent features |
| Speech | faster-whisper, OpenCC, Piper voice models |
| Music | mpv; ffmpeg alternative |
| Audio format | 16 kHz, mono, signed 16-bit PCM WAV |

The firmware is configured for the board's **16 MB flash partition layout** to accommodate bundled fonts. Flashing a new partition table may make existing filesystem contents incompatible.

## Repository layout

```text
ESP32-Local-Ai-Chatbot/
├── src/                  # ESP32 firmware
├── host/                 # USB client, speech adapters, voice agent
│   ├── README.md         # Detailed host setup and protocol reference
│   ├── box3.py           # Host-side device control
│   ├── voice_agent.py    # Standalone voice conversation loop
│   └── offline_speech.py # Speech recognition and synthesis CLI
├── pi/                   # Pi coding-agent extension
│   └── box3.ts
├── tests/                # Host and protocol tests
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

### Wi-Fi setup / Setting Mode

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

### Connect Pi Coding Agent over Wi-Fi

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

### 2. Set up the host USB bridge

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

### 4. Optional Pi extension

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

Supported inline icons include selected faces, robot, microphone, speaker, check, cross, warning, and heart symbols. This is **not a complete Unicode emoji font**. Unsupported glyphs and complex emoji sequences may not render. Mixed-language strings do not receive automatic font fallback.

The UI can show a robot avatar with static expressions (`happy`, `sad`, `listening`, `thinking`, `speaking`, `music`, `error`). Expressions reflect agent state rather than inferred emotions or synchronized lip movement.

## Audio transport

The host and firmware communicate through a line-oriented native USB protocol using `BOX1` requests and acknowledgements. The protocol supports display messages, microphone capture, playback, and cancellation. Current firmware adds checked audio chunks with offsets/CRC32, retry handling, and streaming synchronization.

| Capability | Notes |
| --- | --- |
| Recording | 16 kHz mono PCM16, maximum 10 seconds per captured utterance |
| Playback | 16 kHz mono PCM16 |
| Checked transfers | Chunk offsets and CRC32 integrity checks |
| Streaming | PSRAM ring buffer on supported firmware |
| Microphone | Paused during speaker playback |
| Concurrency | One host operation at a time |

For wire commands, version compatibility, status flags (`audio=pull1`, `vad=1`, `stream=ring1`, `streamrev=4`), and recovery procedures, see [host/README.md](host/README.md).

## Local music

The standalone voice agent can play files from `~/Music` (or a directory selected with `--music-dir`). Spoken song requests are matched against local filenames, decoded with mpv, and streamed to the BOX-3. It does not search online music services or control a separate host-speaker jukebox process.

For an explicit local track, use the agent command:

```text
/music /path/to/song.mp3
```

Listening resumes after playback. USB stalls may still cause audible gaps.

## Testing and diagnostics

```bash
# Python tests (including simulated serial protocol coverage)
python3 -m unittest discover -s tests -p 'test_*.py'

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

Automated tests and successful compilation do not substitute for hardware verification of the microphone, speaker, and native USB link.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Serial port busy | Close PlatformIO monitor, the voice agent, or another bridge client |
| Device not found | Verify native USB data cable, port path, and serial permissions |
| No microphone audio | Inspect device status, I2S initialization, and a saved test WAV |
| No speaker sound | Run `speaker-test`; codec initialization alone is insufficient |
| Corrupted audio / malformed response | Reflash matching firmware, close other serial clients, and retry |
| Playback interruptions | Verify streaming capability and USB transfer health |
| Missing Chinese/Japanese/Korean glyphs | Select the correct display language and check bundled font coverage |
| Speech model missing | Install matching Piper `.onnx` / `.onnx.json` files and confirm model paths |

## Documentation

- [Host setup, offline voice agent, and USB protocol](host/README.md)
- [PlatformIO configuration](platformio.ini)
- [Firmware source](src/)
- [Pi extension](pi/box3.ts)
- [Tests](tests/)

## Project scope

This is a **host-assisted local voice terminal**, not an on-device ESP32 language model. Speech recognition and synthesis can run offline after their models are installed. Pi agent capabilities, tool access, and whether inference requires a network depend on the host configuration. The project does not currently provide full-duplex voice, acoustic echo cancellation, unrestricted emoji rendering, or cloud music search.

## License

No license is declared here. Check the repository for an explicit license before assuming redistribution or modification permissions.


## Wake phrase: Osiris!

Spoken requests now require **Osiris** by default over USB or Wi-Fi:

- Say **“Osiris, what is the weather?”** in one utterance, or
- Say **“Osiris!”**, wait for **Awake!** on the display, then speak one request
  within **15 seconds**.

After one request, the agent returns to waiting for the wake phrase. Unrelated
speech is ignored while waiting, and a standalone wake expires if no request
arrives. Keyboard prompts and `/transport` commands do not need a wake phrase.
The spelling is **Osiris**; matching ignores case and does not require the
exclamation mark.

```bash
host/.venv/bin/python host/voice_agent.py --host 192.168.1.50 --language auto
# Optional: change timeout, keyword, or disable wake gating
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
