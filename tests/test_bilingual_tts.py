"""Language selection and PCM assembly for mixed Chinese/English replies."""
import importlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
speech = importlib.import_module('offline_speech')


class BilingualSpeechTests(unittest.TestCase):
    def test_switches_voices_without_losing_spaces_numbers_or_punctuation(self):
        text = '\u4f60\u597d\uff0cplease check Taipei weather 25 degrees\uff0c\u8b1d\u8b1d\u3002'
        segments = speech.speech_segments(text, 'zh-TW')
        self.assertEqual([lang for lang, _ in segments], ['zh-TW', 'en', 'zh-TW'])
        self.assertEqual(''.join(content for _, content in segments), text)
        self.assertIn('please check Taipei weather 25 degrees', segments[1][1])

    def test_latin_accent_and_apostrophe_stay_in_english_run(self):
        self.assertEqual(speech.speech_segments("Caf\u00e9 isn't bad.", 'zh'),
                         [('en', "Caf\u00e9 isn't bad.")])
        self.assertEqual(speech.speech_segments('123!', 'zh'), [('zh', '123!')])

    def test_segments_are_joined_into_one_pcm_wave_in_original_order(self):
        rendered = []
        def render(text, output, language):
            rendered.append((language, text))
            with wave.open(str(output), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(struct.pack('<h', len(rendered)) * 80)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'reply.wav'
            with patch.object(speech, '_synthesize_single', side_effect=render):
                speech.synthesize('\u4f60\u597d hello world \u8b1d\u8b1d', path, 'zh-TW')
            with wave.open(str(path), 'rb') as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
                pcm = wav.readframes(wav.getnframes())
        self.assertEqual([lang for lang, _ in rendered], ['zh-TW', 'en', 'zh-TW'])
        self.assertEqual(pcm, b''.join(struct.pack('<h', value) * 80 for value in (1, 2, 3)))

    def test_english_reply_uses_english_voice_even_with_chinese_hint(self):
        with patch.object(speech, '_synthesize_single') as render:
            speech.synthesize('Hello world', '/tmp/unused.wav', 'zh-TW')
        render.assert_called_once_with('Hello world', '/tmp/unused.wav', 'en')

    def test_emoji_only_reply_keeps_silent_wave_behavior(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'emoji.wav'
            speech.synthesize('\U0001F916', output, 'zh-TW')
            with wave.open(str(output), 'rb') as wav:
                self.assertEqual(wav.getnframes(), 0)


if __name__ == '__main__':
    unittest.main()
