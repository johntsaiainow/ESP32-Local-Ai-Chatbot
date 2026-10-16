# Osiris Desktop (PyQt6)

This is a desktop port of the Osiris assistant: the window replaces the ESP32
screen and touch controls, and your computer supplies the microphone and speaker.
**No ESP32, USB serial connection, firmware upload, or `voice_agent.py` bridge is required.**

It includes the same 13 color emoji expressions, configurable wake phrase,
15-second initial request window, and 30-second follow-up window after the last
spoken reply finishes. Text arrives progressively and speech is synthesized and
played sentence by sentence, using the existing host speech/backend modules.

## Install and launch

From the repository root, using Python 3.10 or newer:

```bash
python3 -m venv host/.venv
host/.venv/bin/python -m pip install -r host/requirements-desktop.txt
host/.venv/bin/python host/desktop_osiris.py
```

On Debian/Ubuntu, local audio requires PortAudio. If Qt reports a missing xcb
plugin dependency, install the corresponding desktop libraries:

```bash
sudo apt install libportaudio2 libxcb-cursor0 libxkbcommon-x11-0
```

Use a graphical desktop session. On Windows, use `host\.venv\Scripts\python.exe`
in place of `host/.venv/bin/python`. Windows/macOS have not yet been validated;
Linux is the development platform. Microphone permission may be required by the OS.

## Choose a backend

- **pi**: install and configure the existing `pi` coding-agent CLI, with `pi` on
  `PATH`. Its configured model/account is used; the GUI Model field is ignored.
  A persistent RPC process holds the conversation until Stop. Start begins a new
  session; temporary Pi session files are removed at Stop.
- **openai**: export `OPENAI_API_KEY`; enter the desired model in Model, or set
  `BOX3_OPENAI_MODEL` before launch.
- **gemini**: export `GEMINI_API_KEY`; enter Model, or set `BOX3_GEMINI_MODEL`.
- **openclaw**: export `OPENCLAW_GATEWAY_TOKEN` and optionally
  `OPENCLAW_GATEWAY_URL` (default `http://127.0.0.1:18789`). Model defaults to
  `openclaw/default`. Enable the Gateway's Chat Completions endpoint as described
  in the [OpenClaw guide](openclaw.md).

These reuse the existing providers. API keys/tokens come from the process
environment and are not stored by the GUI. OpenAI/Gemini here use API access;
consumer ChatGPT/Gemini app subscriptions are not desktop API credentials.
The language model still runs in Pi's configured backend, the Gateway, or the
cloud provider; the GUI does not bundle a local language model.

## Local speech models

The desktop uses the same local Whisper and Piper models as the host voice
agent. Whisper downloads the chosen model on first use if it is not cached;
startup may take longer that first time. Choose `base` or `tiny` instead of
`small` for faster recognition on slower CPUs, with an accuracy tradeoff.

Piper needs both the `.onnx` model and matching `.onnx.json` configuration:

```text
~/aion-voice/models/zh_TW-huayan-medium.onnx
~/aion-voice/models/zh_TW-huayan-medium.onnx.json
~/aion-voice/models/en_US-lessac-medium.onnx
~/aion-voice/models/en_US-lessac-medium.onnx.json
```

Override the directory with `BOX3_MODELS_DIR`, or individual model paths with
`BOX3_PIPER_ZH` / `BOX3_PIPER_EN`. Existing speech installation instructions in
[the main README](../README.md) also apply. Speech recognition supports automatic
language detection; this first desktop port supplies Chinese and English speech
output, matching the current local Piper backend.

## Use

1. Select the provider and audio devices. Change the wake phrase if desired.
2. Press **Start Osiris**. Model preparation happens in the background. The
   microphone stays off until Start and closes during recognition, model replies,
   and playback, preventing the assistant from hearing its own speech.
3. Say “Osiris”, then your request, or say “Osiris, tell me …” together. After a
   reply, speak again within 30 seconds without repeating the wake phrase.
4. Alternatively, type and press Enter/Send; typed messages bypass the wake gate.
5. Press **Stop** before changing settings. Closing the window also stops the
   worker and waits for cleanup. An in-progress Whisper/Piper operation must
   finish before shutdown; network requests are cancelled where supported.

For keyboard-only use, uncheck **Listen for wake phrase** and **Speak replies**.
This skips both speech model loading and audio device initialization in the
conversation worker. Device enumeration in the UI does not open the microphone.

The microphone/speaker lists use your system's audio devices. Prefer a physical
microphone over a speaker-monitor/loopback source. The app converts the selected
device's native sample rate to 16 kHz for recognition and converts speech back to
the speaker's native rate. Increase Voice threshold if room noise triggers too
many recordings; lower it if speech is missed. Pause to send defaults to 0.6 s.
Using headphones can improve recognition in noisy rooms.

Non-secret preferences are saved with Qt `QSettings`. Conversation text is shown
in memory; the GUI does not save a transcript. Provider/Pi storage policies still
apply. Settings on Linux normally live under `~/.config/Osiris/Desktop.conf`.

Wi-Fi provisioning, GPIO, board display calibration, and firmware flashing remain
ESP32 features and are not needed by the desktop application. This port focuses
on conversation; the firmware/host local music command is not yet exposed in the GUI.

## Implementation and verification

- `host/desktop_osiris.py`: PyQt6 window, settings, queued worker events.
- `host/desktop_core.py`: desktop capture/playback, wake gate, turn orchestration.
- Existing `pi_rpc.py`, `chat_backends.py`, `offline_speech.py`, and
  `streaming_reply.py` provide persistent model connections and streamed speech.
- `host/desktop_assets/`: unchanged original firmware emoji PNGs; licenses remain
  under `third_party/lgfx_emojis/`.

Run the desktop tests without recording audio or making model requests:

```bash
QT_QPA_PLATFORM=offscreen host/.venv/bin/python -m unittest discover -s tests -p test_desktop.py -v
```

Tests cover native-rate PCM conversion, keyboard-only isolation, wake gating,
follow-up timing after playback, cancellation, streamed UI text, preferences,
and an actual Qt worker lifecycle. Physical microphone/speaker quality and live
provider conversation still require a manual desktop session.
