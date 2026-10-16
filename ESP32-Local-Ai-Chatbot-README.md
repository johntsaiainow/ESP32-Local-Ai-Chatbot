# ESP32 Local AI Chatbot

### ESP32-S3-BOX-3 · USB Voice Terminal · Pi Coding Agent · Offline Speech

A multilingual, voice-enabled AI terminal built around the **ESP32-S3-BOX-3**. The ESP32 handles the display, microphone, speaker, and USB audio transport; a connected Linux/macOS host handles speech recognition, speech synthesis, and interaction with the **Pi coding-agent CLI**.

The project combines embedded firmware, a Python host bridge, a TypeScript Pi extension, and a standalone voice agent. **LLM inference does not run on the ESP32.** Speech recognition and synthesis can run locally on the host after their models are installed; Pi's model/provider configuration determines where conversational inference runs.

## Features

- **Interactive voice conversations:** capture microphone audio, transcribe speech, send text to Pi, display replies, and play synthesized responses.
- **Offline speech processing:** faster-whisper for multilingual speech recognition, OpenCC for Traditional Chinese conversion, and Piper for local speech synthesis. Optional Vosk recognition is supported.
- **Multilingual display:** English, Simplified Chinese, Traditional Chinese, Japanese, and Korean using bundled LovyanGFX efont resources.
- **Compact emoji rendering:** selected custom 16-pixel icons, including robot, microphone, speaker, smile, warning, and status symbols.
- **Robot face states:** happy, sad, listening, thinking, speaking, music, and error expressions.
- **USB bridge:** serial command protocol for text, recording, playback, and device status, with checked audio chunks and CRC32 validation.
- **Continuous playback:** PSRAM-backed ring-buffer streaming on compatible firmware; local music playback through mpv or ffmpeg decoding.
- **Pi integration:** `box3_display`, `box3_say`, and `box3_listen` tools, plus an explicit `/box-listen` command.
- **Diagnostics and tests:** audio loopback, speaker tone generation, host protocol tests, and a C++ UTF-8 test.

## Architecture

```text
  ESP32-S3-BOX-3                         Host computer (Linux/macOS)
┌──────────────────────┐      USB      ┌──────────────────────────────┐
│ Microphone / I2S     │──────────────▶│ Python BOX-3 host bridge     │
│ Display / Robot face │◀──────────────│ faster-whisper / OpenCC      │
│ Speaker / I2S        │               │ Piper / optional Vosk        │
│ Audio buffers / VAD  │               │ Pi coding-agent CLI         │
└──────────────────────┘               │ Optional local music decoder│
                                       └──────────────────────────────┘
```

The device performs audio capture, amplitude-based utterance endpointing, display rendering, and PCM playback. The host performs transcription, text processing, agent orchestration, and speech synthesis. Microphone capture and speaker playback are sequential; acoustic echo cancellation is not implemented.

## Repository layout

```text
.
├── src/                     # ESP32 firmware sources
├── host/                    # Python USB bridge, voice agent, speech adapters
│   ├── README.md            # Detailed setup, protocol, and diagnostics
│   ├── box3.py              # Device control CLI
│   ├── voice_agent.py       # Standalone conversational voice agent
│   ├── offline_speech.py    # Local speech adapters
│   ├── requirements.txt
│   └── requirements-offline.txt
├── pi/
│   └── box3.ts              # Pi coding-agent extension
├── tests/                   # Host protocol and UTF-8 tests
├── platformio.ini           # PlatformIO project configuration
└── README.md
```

## Requirements

**Hardware:** ESP32-S3-BOX-3, a USB data cable connected to the board's native USB port, and a host computer capable of running the selected speech models.

**Firmware tools:** PlatformIO and the toolchain/dependencies resolved by `platformio.ini`.

**Host tools:** Python 3, a Pi coding-agent CLI installation for AI conversations, and appropriate local model files. The offline voice workflow also requires the system `ffmpeg` executable; local music playback uses `mpv` by default. The host bridge uses POSIX exclusive serial access and targets Linux/macOS.

## Quick start

### 1. Clone the project

```bash
git clone https://github.com/johntsaiainow/ESP32-Local-Ai-Chatbot.git
cd ESP32-Local-Ai-Chatbot
```

### 2. Build and upload the firmware

```bash
pio run
pio run --target upload
```

For initial diagnostics, use a serial monitor at **115200 baud**. Close the monitor before running the host bridge: only one application can own the USB serial port at a time.

The firmware uses a 16 MB flash partition layout to accommodate bundled fonts. Updating the partition layout can invalidate previously stored filesystem contents.

### 3. Install the Python host bridge

```bash
python3 -m venv host/.venv
host/.venv/bin/pip install -r host/requirements.txt
export BOX3_PYTHON="$PWD/host/.venv/bin/python"
export BOX3_PORT=/dev/ttyACM0
```

Replace `/dev/ttyACM0` with the actual device path. To find available serial ports:

```bash
"$BOX3_PYTHON" -m serial.tools.list_ports
```

### 4. Verify the device

```bash
"$BOX3_PYTHON" host/box3.py status
"$BOX3_PYTHON" host/box3.py display --language en -- 'Pi is ready!'
"$BOX3_PYTHON" host/box3.py display --language zh -- '你好 🤖 ✅'
"$BOX3_PYTHON" host/box3.py speaker-test
"$BOX3_PYTHON" host/box3.py record /tmp/box3-mic.wav --seconds 5
"$BOX3_PYTHON" host/box3.py play /tmp/box3-mic.wav
```

The device status can report capabilities such as `mic=1`, `speaker=1`, `audio=pull1`, `vad=1`, `stream=ring1`, and `face=1`, depending on firmware revision. Codec initialization is **not** proof of audible output: verify recording and speaker playback with actual hardware.

## Run the standalone voice agent

Install the offline speech dependencies:

```bash
host/.venv/bin/pip install -r host/requirements-offline.txt
```

Install the required system tools and configure your local Piper voice files and Pi CLI. Speech models are **not bundled** with the repository. Whisper models are downloaded to the local cache on first use; subsequent runs can use cached files.

```bash
"$BOX3_PYTHON" host/voice_agent.py --language auto
```

Other supported modes:

```bash
"$BOX3_PYTHON" host/voice_agent.py --language zh
"$BOX3_PYTHON" host/voice_agent.py --language en
"$BOX3_PYTHON" host/voice_agent.py --keyboard-only
"$BOX3_PYTHON" host/voice_agent.py --capture-mode window --record-seconds 4
"$BOX3_PYTHON" host/voice_agent.py --language zh --silence 1.5
```

By default, device-side amplitude-based capture preserves a short pre-roll, waits for voice activity, and stops after a pause or the recording limit. It is **not** a neural voice activity detector. The agent shows the transcript and Pi's reply on the display, including paginated long messages, and plays synthesized speech through the BOX-3 speaker.

### Speech model configuration

| Component | Default or configuration |
| --- | --- |
| Recognition | faster-whisper multilingual `small`, CPU int8 |
| Whisper cache | `.cache/voice-models/whisper` |
| Alternate Whisper model | `--whisper-model` or `BOX3_WHISPER_MODEL` |
| Piper/Vosk model root | `~/aion-voice/models` or `BOX3_MODELS_DIR` |
| Chinese Piper voice | `zh_TW-huayan-medium.onnx` or `BOX3_PIPER_ZH` |
| English Piper voice | `en_US-lessac-medium.onnx` or `BOX3_PIPER_EN` |
| Optional Vosk models | `BOX3_VOSK_ZH` and `BOX3_VOSK_EN` |

Piper models require their matching `.onnx.json` files. Mixed Chinese/English speech is synthesized in separate language runs and combined into a 16 kHz mono WAV; it does not use a single bilingual voice.

## Pi coding-agent integration

Load the included extension explicitly:

```bash
pi -e ./pi/box3.ts
```

The extension provides:

| Tool | Purpose |
| --- | --- |
| `box3_display` | Show short text and supported emoji (`en`, `zh`, `zh-TW`, `ja`, `ko`) |
| `box3_say` | Synthesize speech through the configured host adapter and play it |
| `box3_listen` | Record speech and return an English/Chinese transcript |

The `/box-listen en` and `/box-listen zh` commands record a five-second utterance and submit the transcript as a new Pi message. Listening is initiated explicitly in extension mode; it is not an always-on microphone service.

**Serial-port ownership:** do not run the Pi extension and standalone voice agent simultaneously. Both need exclusive access to the same device.

## Local music playback

Place tracks under `~/Music`, or supply an alternate directory:

```bash
"$BOX3_PYTHON" host/voice_agent.py --music-dir /path/to/music
```

The standalone agent recognizes supported spoken song requests and also accepts `/music /path/to/song.mp3`. Files are decoded on the host and streamed as mono 16 kHz PCM to the BOX-3. This is a **local file player**, not an online music search or streaming-service integration. Voice listening pauses during playback.

## Display and character support

The firmware exposes a helper for multilingual text:

```cpp
printLocalizedText(10, 100, "\uC548\uB155\uD558\uC138\uC694",
                   DisplayLanguage::Korean);

printLocalizedText(10, 10, "Agent ready \U0001F916 \u2705",
                   DisplayLanguage::English);
```

Supported display languages are English, Simplified Chinese, Traditional Chinese, Japanese, and Korean. Glyph coverage is limited to bundled font sets; arbitrary mixed-script fallback is not implemented. Emoji support is a curated collection of custom icons rather than a full Unicode emoji font. Unsupported emoji sequences, flags, and skin-tone combinations are not supported.

## USB protocol and audio format

The bridge uses newline-terminated `BOX1` requests with sequential `OK`/`ERR` replies. Its commands cover device status, text display, fixed and variable-duration recording, checked reads, PCM playback, chunk upload, cancellation, and firmware-dependent streaming/synchronization capabilities.

| Property | Value |
| --- | --- |
| Transport | Native USB serial |
| Audio | 16 kHz, mono, signed 16-bit little-endian PCM |
| Message framing | LF-terminated ASCII commands; hex-encoded text/audio payloads |
| Integrity | CRC32 on checked audio transfers |
| Recording limit | Up to 10 seconds per captured utterance |
| Command concurrency | One active host operation at a time |

Newer firmware supports a PSRAM-backed ring buffer and stream synchronization/retry mechanisms. Host and firmware revisions must match. See [host/README.md](host/README.md) for the detailed command table, buffer sizes, revision-specific capabilities, and recovery behavior.

## Tests and validation

```bash
# Firmware build
pio run

# Python protocol tests (including simulated serial behavior)
python3 -m unittest discover -s tests -p 'test_*.py'

# Native UTF-8 decoder test
g++ -std=c++17 tests/test_utf8.cpp -o /tmp/box3-test-utf8
/tmp/box3-test-utf8
```

For hardware validation, check the status response, record and replay a short microphone sample, and run `speaker-test`. A successful firmware build or simulated serial test does not establish microphone, codec, USB, or acoustic correctness on physical hardware.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Serial port busy | Close PlatformIO Serial Monitor and any other BOX-3 client. |
| Device not detected | Use the native USB data port and a data-capable cable; inspect serial ports. |
| Malformed audio response | Reflash matching firmware; avoid concurrent serial clients. |
| No audible speaker output | Run `speaker-test`; check codec status and the physical output path. |
| Missing or partial microphone capture | Check `capture` and `vad` status, inspect diagnostic WAV, and review I2S framing notes. |
| Speech models not found | Set the Piper/Vosk paths and ensure each Piper `.onnx.json` file is present. |
| Poor recognition | Try `--language zh`/`en`, adjust `--threshold` and `--silence`, or inspect a saved recording. |
| Streaming interruptions | Verify `stream=ring1` and stream revision support; USB stalls may still produce audible gaps. |
| Unsupported characters | Use the correct display language and a glyph present in the bundled fonts. |

## Current limitations

- The ESP32 acts as an embedded interface; it does not execute the LLM.
- Recognition and synthesis can be local, but Pi model execution depends on the user's Pi configuration.
- Audio capture and playback are sequential, without echo cancellation.
- The display supports limited font and emoji sets rather than unrestricted Unicode.
- Replies are displayed after Pi finishes; token-by-token LLM streaming is not implemented.
- Local music is filename-based and does not provide online search or playlist management.
- Model weights and required voice assets must be installed separately.

## Documentation

For full host setup, command details, environment variables, protocol revisions, and hardware diagnostics, read **[host/README.md](host/README.md)**.

## Project status

An actively developed embedded AI voice-terminal project. Protocol behavior and firmware capabilities may evolve; keep the host tools and firmware on compatible revisions and verify changes on physical hardware.

## License

No license file was visible in the repository at the time this README was prepared. Do not assume a particular open-source license; add a `LICENSE` file if you intend to grant reuse and redistribution rights.
