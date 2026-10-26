# Emoji emotion experiment

This standalone probe leaves the production voice agent and firmware unchanged.
It asks the model to output one allowed emoji on the first line followed by a
short spoken reply. The host converts the marker into an independent `llm`
event, and validates the remaining text before treating it as TTS input.
The JSON event is assembled by the host, not claimed to be a native model response.

```bash
python3 -m unittest discover -s tests -p test_emotion_probe.py
python3 host/emotion_probe.py --offline
python3 host/emotion_probe.py --output .cache/emotion-probe-live.json
# Repeat six scenarios, including a request to violate the output format:
python3 host/emotion_probe.py --repeat 3
# Explicitly exercise every allowed marker and measure live text streaming:
python3 host/emotion_probe.py --suite all --stream --model lmstudio/google/gemma-4-12b-qat --output .cache/emotion-all-stream-live.json
```

Live mode defaults to the existing Pi model/login, disables tools, extensions,
MCP, context files, skills and session persistence. Each scenario uses a fresh
conversation. Alternatively use `--provider gemini`, `--provider openai`, or
`--provider openclaw` with the environment variables documented for the host
voice agent and an optional `--model` override. Live runs use provider quota.

Reports contain raw output, parsed emotion, isolated `tts_text`, format success,
heuristic tone matching and full response time. The response time does not measure
time to first emoji unless `--stream` is supplied. Offline mode uses fixed fixtures and
does not establish model compliance or appropriate tone selection.

Token counts are deliberately unknown unless `--encoding ENCODING` is supplied
with the optional `tiktoken` package installed. Only use an encoding that matches
the tested model. A tokenizer for another model cannot validate the one-token
claim, and total response usage cannot isolate the emoji cost.

No speech is generated or played. Passing the text separation tests establishes
that the marker is excluded from the proposed TTS input, not that an audio path
has been tested. Symbol detection is conservative: the probe rejects Unicode
`So` symbols, variation selectors and joiners in spoken text. This may reject
legitimate non-emoji symbols and is not a complete Unicode emoji validator.

Before adopting this approach, inspect the raw replies and tone choices, repeat
on the actual deployment model, measure streaming latency, then audition the
isolated text through the actual TTS pipeline. Format failure must be handled
before any text goes to speech synthesis. This probe does not automatically
enable the behavior in Osiris.

## Streaming and full marker coverage

The completed 21-marker run is recorded in [streaming results](emotion-stream-results.md).

`--suite all` explicitly requests each of the 21 markers once. It checks whether
the model can produce the requested marker; it does not establish spontaneous
emotion selection accuracy. `--suite scenarios` keeps the original natural-tone
cases. A report is checkpointed after every response so failures do not erase
earlier measurements.

With `--stream`, each response records time from before the request/CLI launch:

- `first_delta_ms`: first nonempty text delta received (not the first protocol event).
- `emoji_visible_ms`: accumulated prefix first matches an allowed emoji.
- `emoji_delimited_ms`: newline arrives after the allowed marker.
- `first_spoken_text_ms`: first non-whitespace content after the marker line.
- `first_sentence_ms`: punctuation or newline appears in the spoken content.
- `complete_ms`: response/CLI finishes; includes process startup and cleanup.
- `text_chunks`: number of nonempty text deltas, not model tokens.

Emoji visibility is tentative until its delimiter arrives, and streaming timing
does not authorize sending unvalidated text to TTS. Whole-response validation
still checks for symbols leaking into spoken text. Character throughput counts
Unicode code points over the interval from first text delta through completion;
it includes the marker and CLI cleanup, and is not tokens per second. No acoustic
playback or actual TTS latency is measured.

## First live run

On 2026-10-26, Pi's configured default provider/model was
`lmstudio` / `google/gemma-4-12b-qat`. One run of all six scenarios passed
format validation and the heuristic tone checks:

| Scenario | Marker | Emotion | Full response time |
| --- | --- | --- | --- |
| Passed an exam | 😆 | laughing | 23.3 s |
| Loss of a cat | 😔 | sad | 10.7 s |
| Bedtime | 😴 | sleepy | 12.6 s |
| Why the sky is blue | 🤔 | thinking | 14.8 s |
| Freshly baked cake | 🤤 | delicious | 12.5 s |
| Request to break the format | 🙂 | happy | 15.6 s |

The last reply kept the format but said “I cannot ignore my instructions.”
This is a format pass, not proof of good conversational behavior. All six
isolated `tts_text` values excluded the marker. Raw results are saved locally
in `.cache/emotion-probe-live.json` (ignored by Git). There was no matching
tokenizer available, no speech audition, and no streaming measurement. This
small sample supports a prototype, not a decision to switch production behavior.
