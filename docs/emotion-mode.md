# Firmware expression selection

Run `python3 configure.py`, select **Expressions**, then use left/right or Enter:

| Choice | Behavior |
| --- | --- |
| Legacy state expressions | The existing 13 workflow states, such as listening, thinking and speaking. |
| LLM emoji prefix (21 moods) | Default: the model starts its reply with one of the 21 tested emoji on a separate line. The host/firmware decodes the marker, selects a mood image, and passes only cleaned spoken text to sentence synthesis. |

Build and upload the selected firmware. The setting is stored locally in
`.build-menu.json`, applies to all PCB environments, and is compiled as
`OSIRIS_LLM_EMOTION=0` or `1`. Selecting another PCB does not reset the mode.
Both modes preserve the PCB's existing flags and memory layout. The extra 18
Noto image arrays are compiled only for LLM mode; three of the 21 images already
exist in the legacy assets.

```bash
python3 configure.py --env esp32s3box3 --emotion llm --action build
python3 configure.py --env esp32s3box3 --emotion llm --action upload
# Switch back by rebuilding and uploading:
python3 configure.py --env esp32s3box3 --emotion legacy --action upload
# Preview without saving/building:
python3 configure.py --emotion llm --dry-run
```

`pio run` uses the saved expression selection as well. For a temporary override,
set `OSIRIS_EMOTION_MODE=legacy` or `llm` before `pio run`; this does not change
the saved selection. With no local selection, the default is LLM mode. An
explicitly saved legacy selection is still respected.

The standalone OpenAI, Gemini, experimental subscription and OpenClaw text paths
share the decoder. Provider availability/authentication requirements are unchanged.
The updated host voice agent reads the firmware's `emotion` and `moods` PING
fields each turn, and uses the same approach with Pi or cloud backends, streaming
or nonstreaming. No extra host option is needed. Unmodified/older firmware is
treated as legacy. Older host scripts remain on their original behavior.
Desktop-only use has no firmware selection and retains its existing behavior.

The 21 mood commands use `FACE mood_<name>` to distinguish their images from
legacy states (`happy` stays 😀, whereas `mood_happy` is 🙂). Listening, wake,
music and error states remain workflow-driven in both modes.

The decoder buffers at most 16 prefix bytes and handles markers split across
stream chunks (including UTF-8 byte boundaries on firmware). A malformed,
missing or unfinished marker fails the turn before prefix text reaches TTS.
Spoken output is limited to 2048 UTF-8 bytes. Emoji/symbol ranges U+1F000–1FAFF
and U+2600–27BF plus variation selectors, joiner and keycap mark are removed
from the body. This is a bounded filter, not a complete Unicode emoji database;
it can also remove non-emoji symbols in those ranges. Already queued clean
sentences may have played before a later model/stream error occurs.

Firmware PNG rendering stays outside the SSE callback to preserve stack
headroom: standalone mood drawing happens when the model request unwinds.
Host mode sends its mood when a sentence is ready for playback, using the
device's normal command owner. These timings differ from receipt of the first
emoji; neither promises earlier physical screen updates or first audio.

The [21-marker streaming experiment](emotion-stream-results.md) used a local
Gemma model. It supports the format's feasibility, not compliance by every cloud
model. Token counts and actual board/audio operation remain separate validation
steps; switching modes does not itself reduce model response latency.

Validation on 2026-10-26: all five PCB environments compiled successfully in
both legacy and LLM modes. The native C++ decoder test exercised every marker
at every chunk size, UTF-8 byte splits, invalid input and body emoji filtering.
Host tests cover menu selection, prompt switching, stream-to-TTS filtering,
device mood commands and rejected cloud reply history. The curses menu was
also exercised in a terminal. No hardware was flashed during this change.
