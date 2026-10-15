# ESP32-S3-BOX-3 Display and Microphone

The [USB bridge setup](host/README.md) connects this firmware to the Pi coding-agent
CLI, including display/emoji commands, microphone recording, speaker playback,
and configurable host speech adapters for English/Chinese recognition and speech.
The [offline voice agent](host/voice_agent.py) adapts the Whisper/OpenCC/Piper workflow
to the BOX-3 microphone and speaker, with keyboard input and a concise Pi reply.

Build with `pio run` and upload with `pio run --target upload`. Open the Serial
Monitor at 115200 baud to view microphone levels and initialization messages.

Source comments, identifiers, and normal interface messages are English.
The startup screen includes Chinese, Japanese, and Korean font samples.

## Multilingual text

`printLocalizedText(x, y, text, language)` renders UTF-8 text using a bundled
16-pixel font selected by `DisplayLanguage`:

- `English`
- `SimplifiedChinese`
- `TraditionalChinese`
- `Japanese`
- `Korean`

For example, this ASCII source string displays a Korean greeting:

```cpp
printLocalizedText(10, 100, "\uC548\uB155\uD558\uC138\uC694",
                   DisplayLanguage::Korean);
```

Choose the matching language for each text segment. The helper restores the
previous font afterward. Glyph coverage is limited to the bundled LovyanGFX
efont character sets; there is no automatic font fallback for arbitrary mixed
language strings. No SD card or external VLW font file is needed for these fonts.

## Emoji

`printLocalizedText` also renders compact color icons inline with UTF-8 text:
grinning face (U+1F600), smiling face (U+1F642), thinking face (U+1F914),
robot (U+1F916), microphone (U+1F3A4), speaker (U+1F50A), check (U+2705),
cross (U+274C), warning (U+26A0), and heart (U+2764).

```cpp
printLocalizedText(10, 10, "Agent ready \U0001F916 \u2705",
                   DisplayLanguage::English);
```

These are custom 16-pixel icons, not a complete Unicode emoji font. Variation
selectors are ignored. Unsupported supplementary-plane symbols display a boxed
placeholder. Joined sequences, flags, and skin tone combinations are not
supported. The startup screen shows a sample row. USB transport is implemented;
offline multilingual speech uses Whisper, OpenCC, and Piper on the host.
See the USB setup guide for model paths and the standalone voice agent.

The UTF-8 decoder can be tested on the host with:

```sh
g++ -std=c++17 tests/test_utf8.cpp -o /tmp/box3-test-utf8
/tmp/box3-test-utf8
```

The project uses `default_16MB.csv` to fit the bundled fonts in the board's
16 MB flash. Upload through PlatformIO to install the matching partition table
along with the firmware. Existing filesystem contents may be incompatible with
the changed partition layout.
