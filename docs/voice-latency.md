# Voice latency and streaming

The default voice path now overlaps model generation, sentence synthesis and
playback. This reduces time to the first spoken sentence without waiting for
the entire answer/audio download. It is still a turn-based assistant: the mic
is paused during replies, and this does not add acoustic echo cancellation or
interruptible, full-duplex Realtime/Live sessions.

## ESP32 direct mode

- Default end-of-speech silence is **600 ms**, down from 1000 ms. For longer
  natural pauses, add `-DOSIRIS_CLOUD_SILENCE_MS=1000` to your board's existing
  PlatformIO build flags (valid range 250–5000 ms).
- OpenAI Responses, Gemini text, OpenClaw Chat Completions and the experimental
  subscription adapter consume SSE text deltas. Complete sentences enter a
  bounded queue serviced by a separate speech task. UTF-8 and decimal numbers
  remain intact across packet boundaries; long clauses are bounded too.
- OpenAI speech downloads raw 24 kHz mono PCM into a **96 KiB PSRAM ring**.
  A dedicated I2S task resamples to 16 kHz and starts after **250 ms** of audio
  (or a shorter completed turn). The ring spans sentence boundaries, allowing
  the next speech request to download while previous audio plays. Receiving
  and playback overlap.
- Gemini TTS 3.1+ uses SSE PCM chunks; older Gemini TTS models retain buffered
  audio **per sentence**. No configured model is automatically replaced.
- Separate persistent HTTP/TLS connections serve STT/model requests and speech.
  OpenClaw has its own connection/token. Firmware reuses sockets within a turn
  and closes them before idle, avoiding expired keep-alive sockets on wake-up.
  Redirects remain disabled. Broken
  requests are not automatically replayed; this avoids repeating agent actions.
- Standalone STT still uploads the WAV **after endpoint detection**. This is not
  cloud ASR while you speak; that requires a separate Realtime/Live transport.

Sentence boundaries can introduce small pauses or voice/prosody changes.
Multiple TTS requests can change provider billing compared with one large
request. A network failure, refusal or incomplete final response may arrive
**after an earlier sentence was spoken**; already spoken audio cannot be undone.
The remaining queue is discarded on failure, the failure is reported, and a
failed native turn is not saved as a completed conversation turn. No provider
fallback is made.

Implementation follows [official OpenAI streaming documentation](https://developers.openai.com/api/docs/guides/streaming-responses),
[OpenAI streaming speech](https://developers.openai.com/api/docs/guides/text-to-speech),
and [Gemini speech streaming](https://ai.google.dev/gemini-api/docs/generate-content/speech-generation).

## Host mode

- Persistent Pi RPC, OpenAI, Gemini and OpenClaw feed sentence text to a synthesis
  worker. A small audio queue allows the next sentence to synthesize during
  playback. Only the main thread sends device commands, so USB/TCP requests
  cannot interleave between workers.
- Configured Chinese and English Piper voices load before listening and stay
  in memory across sentences and turns. `--no-tts-warmup` restores lazy loading.
  Missing voice files are skipped at warmup and reported if needed for synthesis. Native
  PCM resampling avoids launching a Piper process and FFmpeg for every sentence.
  The original command-line synthesis path remains available for diagnostics.
- Whisper remains resident; the default beam size is now **1**. Use
  `--whisper-beam-size 5` for the previous search width if recognition worsens.
- Default silence is **0.6 seconds**; `--silence 1.0` restores the old pause.
- Recording defaults to the stable `LISTEN` plus checked `READ` pull protocol,
  including firmware that advertises `listenstream=1`. The experimental Wi-Fi
  `LISTENSTREAM` path has produced wake-up timeouts on hardware and is disabled
  by default. Explicit `--stream-capture` enables it for diagnostics. Model/TTS
  reply streaming remains enabled independently. Whisper decodes the completed
  recording, rather than emitting live transcripts.
- Host SSE connections reuse sockets. Pi now uses one RPC process across turns,
  initialized before listening. Session history survives transport reconnections.
  Tools and model processing can still remain a significant cost. RPC failures
  stop the failed turn; a later explicit request can restart the process using
  the same session file. Submitted prompts are never automatically replayed.

To compare against full-response host behavior:

```bash
host/.venv/bin/python host/voice_agent.py --host DEVICE_IP \
  --provider openclaw --no-stream-replies --silence 1.0 --whisper-beam-size 5
```

Omit `--no-stream-replies` to enable the default pipeline. That flag also uses
legacy Piper CLI synthesis. Piper voice files and the configured provider must
already be available; missing models are reported, not downloaded silently by
this pipeline. Default Pi mode requires RPC commands and `agent_settled` events.
`--pi-one-shot` restores per-request JSON streaming; `--no-stream-replies`
restores complete CLI replies. Interactive extension dialogs in RPC are
cancelled on the voice interface, never automatically approved.

## Read the timings

In direct mode, use the serial monitor (`pio device monitor -b 115200`) and look
for `LATENCY` lines. Logs contain durations and sizes, not credentials/audio.

| Field / stage | Meaning |
| --- | --- |
| `stt elapsed_ms` | WAV request/upload, cloud transcription and parsing |
| `audio_ms` | Recorded audio length, including pre-roll/trailing silence |
| `endpoint_ms` | Configured silence threshold, not a measured server delay |
| `llm first_text_ms` | First text delta relative to starting the model request |
| `llm elapsed_ms` | Model stream reception, including queue backpressure |
| `tts_stream first_audio_ms` | Snapshot of first I2S write relative to the first speech download; see below |
| `tts_stream underruns` | Cumulative times the playback task waited for network audio after starting |
| `turn first_audio_ms` | First I2S write relative to endpoint handling, including STT and the first sentence |
| `turn elapsed_ms` | Endpoint handling through the end of playback |

Zero `turn first_audio_ms` means audio never started. Per-request
`tts_stream first_audio_ms` is a snapshot: zero can also mean the prefill has
not played yet, or that first audio belonged to a previous sentence.
`tts_stream elapsed_ms` measures downloading/enqueuing, while `turn` includes
draining the playback ring. The I2S timestamp measures a
successful DMA write; it is not a microphone measurement of acoustic output.
The silence wait precedes `turn`, so add the configured endpoint interval when
comparing to the moment you stopped speaking.

Host output similarly logs `capture_receive`, `stt`, `llm_first_text`, `llm`,
per-sentence `tts` and `turn`. `capture_receive` includes waiting for speech and
the recording itself. Host `turn` begins after transcription; its
`playback_upload_start` is when upload starts, **not** when the speaker emits
sound. Do not compare these values directly to native `first_audio_ms`.

To identify the remaining bottleneck, repeat the same short question several
times using the same model/network, compare cold and warm requests, and record
STT, first text and first audio. Mock tests and builds validate behavior, but
cannot establish a real-world latency improvement or promise a response time.


## Disconnecting at wake-up

Firmware logs `BOOT reset_reason=...`, `WIFI disconnected reason=...`, and
`VOICE` lines with stack and internal heap headroom. A new `BOOT` line indicates
a restart; a `WIFI disconnected` line indicates the station link dropped. A
`VOICE error=Cloud HTTP ...` line can instead indicate an API/TLS connection
failure while Wi-Fi stays connected. Capture these lines and any panic/backtrace
when reporting a wake-up problem.

The main loop and speech task use 16 KiB stacks. SSE callbacks only collect text
and enqueue sentences; display/PNG rendering runs after the HTTP callback stack
unwinds. The PCM task/ring starts only when a sentence is ready, and connections
are released even for wake-only or failed transcription turns. These changes
reduce wake-up resource pressure; actual restart causes still require device logs.


If the display shows `WiFi offline` without a new `BOOT` line, inspect the
`WIFI disconnected reason=...` entry rather than assuming a restart. Firmware
now supplements SDK auto-reconnect: after an established connection is lost it
waits five seconds, then requests reconnection with increasing intervals up to
30 seconds. The display shows `WiFi reconnecting...` during recovery. Recovery
pauses while the Settings portal owns networking and never erases credentials.
This restores connectivity after transient failures; the disconnect reason is
still needed to diagnose a recurring wake-triggered drop. If the device retains
its IP and only `VOICE error` appears, the problem is the service connection,
not the station link, and station reconnection is not requested.


`Via: USB` after a host timeout does not establish a Wi-Fi station failure.
Previously, releasing a TCP controller reset the display to USB even without a
USB host. Firmware now shows `Via: Offline` until another controller connects,
while the IP/status line separately reports Wi-Fi connectivity. The host now
catches capture/recognition/wake-screen failures and reconnects the same transport;
it keeps the Pi session and discards the failed utterance rather than replaying it.
Restart the updated host script to use stable capture; a firmware upload is only
needed for the improved display label. Host errors include the failing command,
which is needed to diagnose any further disconnect.

## Pi takes tens of seconds before the first sentence

Default RPC mode logs `pi_rpc_ready` once during startup and `pi_agent_start`,
`pi_first_text` and `pi_complete` relative to each submitted prompt. The
compatibility `--pi-one-shot` mode logs `pi_first_event` (first JSON record)
and measures from CLI launch. `pi_tool_start` and `pi_tool_end`
identify each tool by name and elapsed time, without logging tool arguments or
results. Tool `duration_ms` measures when the host receives its start/end events.
It includes any stdout/queue backpressure and is not a server-side measurement.

The speech pipeline logs `reply_first_delta` and `reply_first_sentence` relative
to starting the reply. Compare them to find time spent waiting for a sentence
boundary. The first Chinese clause can be released at a comma after at least
24 characters. Piper logs `tts_model_load` on cold voice loads; that time is
included in the containing `tts` measurement, not added again.

For example, `playback_upload_start=36722` and first-sentence `tts=2437` leave
about 34.3 seconds for Pi, sentence framing, queues and display commands. Those
numbers alone cannot separate model time from weather-tool time. `turn=46207`
means playback finished at 46.2 seconds; it is not time to first sound. A
capture's `elapsed_ms` also includes onset waiting and recording, so do not
attribute all of it to audio transfer. Zero playback underruns indicates the
playback task did not report starvation on that particular reply.

These host-only diagnostics need a script restart, not a firmware upload.


## Persistent Pi and startup warmup

Keep using the usual host command; no firmware change is needed:

```bash
host/.venv/bin/python host/voice_agent.py --host 192.168.86.210 --language auto
```

Startup now prepares Piper voices and initializes Pi RPC before announcing
that listening is ready. This shifts one-time loading to startup rather than
the first reply, and removes repeated CLI initialization on subsequent turns.
It does not remove model reasoning, provider queueing, or live-data tool time.
Pi is instructed to retrieve fresh weather data for current-weather requests;
compare runs with the same tool usage rather than assuming a cached answer
proves faster live lookup.

For comparison, add `--pi-one-shot --no-tts-warmup` to restore per-request Pi
startup and first-use Piper loading while keeping reply streaming. Tests use a
synthetic RPC subprocess to verify process reuse, cancellation, completion and
no prompt replay; actual performance needs another device/provider measurement.
