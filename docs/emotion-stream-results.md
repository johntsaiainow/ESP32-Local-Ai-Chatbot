# All 21 emoji markers: streaming results

Test date: 2026-10-26. Model: `lmstudio/google/gemma-4-12b-qat` through Pi JSON streaming.

One explicit request per marker, in the order below; 21/21 format checks and requested-marker checks passed. This measures marker coverage, not spontaneous emotion selection. All isolated TTS text excluded emoji; no audio was synthesized or played.

Times start before CLI launch and include startup/provider overhead. Later requests were slower; the cause was not diagnosed. These are single samples, not a controlled benchmark or evidence that an emoji prefix speeds up inference. Token counts remain unmeasured.

| Marker | Emotion | First emoji (s) | First spoken text (s) | Complete (s) | Spoken text |
| --- | --- | ---: | ---: | ---: | --- |
| 😶 | neutral | 8.755 | 8.812 | 8.988 | 我收到了你的測試。 |
| 🙂 | happy | 5.856 | 5.906 | 6.074 | 很高興能協助您。 |
| 😆 | laughing | 6.272 | 6.323 | 6.481 | 這太好笑了吧 |
| 😂 | funny | 7.660 | 7.716 | 7.894 | 這真的太搞笑了。 |
| 😔 | sad | 8.988 | 9.040 | 9.250 | 我今天感到有點難過。 |
| 😠 | angry | 5.547 | 5.607 | 5.826 | 你到底在說什麼啊。 |
| 😭 | crying | 6.451 | 6.511 | 6.705 | 真的好難過喔。 |
| 😍 | loving | 7.229 | 7.290 | 7.496 | 我太喜歡這個測試了 |
| 😳 | embarrassed | 7.606 | 7.668 | 7.866 | 真的太尷尬了。 |
| 😲 | surprised | 7.750 | 7.811 | 8.073 | 這簡直太不可思議了！ |
| 😱 | shocked | 8.323 | 8.389 | 8.545 | 這太驚人了 |
| 🤔 | thinking | 9.364 | 9.459 | 9.723 | 我在思考你的要求。 |
| 😉 | winking | 10.410 | 10.495 | 10.786 | 我知道你在測試我的功能。 |
| 😎 | cool | 14.628 | 14.726 | 15.162 | 沒問題，我已經準備好了。 |
| 😌 | relaxed | 20.674 | 20.822 | 21.307 | 現在一切都很平靜。 |
| 🤤 | delicious | 16.010 | 16.168 | 16.996 | 這塊蛋糕看起來真的太誘人了吧。 |
| 😘 | kissy | 26.394 | 26.552 | 27.294 | 這是我送給你的小愛心。 |
| 😏 | confident | 29.972 | 30.129 | 30.720 | 我當然能輕鬆搞定。 |
| 😴 | sleepy | 21.269 | 21.426 | 21.938 | 我要去睡覺了。 |
| 😜 | silly | 20.240 | 20.398 | 20.988 | 我只是在開玩笑啦。 |
| 🙄 | confused | 22.323 | 22.481 | 22.833 | 又是同樣的要求。 |

First emoji: median 8.988 s, range 5.547–29.972 s. First spoken text: median 9.040 s, range 5.607–30.129 s. Full response: median 9.250 s, range 5.826–30.720 s.

Emoji-to-first-spoken-text delay: median 66 ms, range 50–158 ms. Character throughput after the first delta through completion: median 34.62 code points/s, range 13.45–47.21; this is not tokens/s. Eighteen replies included sentence-ending punctuation; the remaining three had to finish before a complete sentence could be established.

Full JSON measurements: `.cache/emotion-all-stream-live.json` (local, ignored by Git). Rerun instructions and metric definitions: [emotion-probe.md](emotion-probe.md).

The `confused` case returned an eye-roll and an irritated sentence. Matching the protocol label does not establish a suitable emotion mapping or polite assistant behavior. Anger and other tones also require product-specific guidance before adoption.
