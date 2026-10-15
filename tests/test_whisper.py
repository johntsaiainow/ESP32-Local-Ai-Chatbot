"""Whisper adapter behavior without a model download or physical BOX-3."""
import importlib
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
speech = importlib.import_module('offline_speech')


class WhisperTests(unittest.TestCase):
    def recognizer(self, language='auto'):
        recognizer = speech.WhisperRecognizer.__new__(speech.WhisperRecognizer)
        recognizer.language = language
        recognizer.model = Mock()
        recognizer.model.transcribe.return_value = (
            iter([types.SimpleNamespace(text=' \u5929\u6c14 check Taipei '),
                  types.SimpleNamespace(text=' weather tomorrow ')]),
            types.SimpleNamespace(language='zh'))
        return recognizer

    def test_auto_transcribes_mixed_text_and_preserves_english_words(self):
        recognizer = self.recognizer()
        with patch.object(speech, 'traditional', side_effect=lambda text: text.replace('\u6c14', '\u6c23')):
            text = recognizer.transcribe(struct.pack('<hhh', -32768, 0, 32767))
        self.assertEqual(text, '\u5929\u6c23 check Taipei weather tomorrow')
        audio = recognizer.model.transcribe.call_args.args[0]
        self.assertEqual(audio.dtype.name, 'float32')
        self.assertEqual(audio.tolist(), [-1.0, 0.0, 32767 / 32768])
        options = recognizer.model.transcribe.call_args.kwargs
        self.assertIsNone(options['language'])
        self.assertEqual(options['task'], 'transcribe')
        self.assertTrue(options['vad_filter'])
        self.assertEqual(options['initial_prompt'], 'Mandarin Chinese and English conversation.')
        self.assertEqual(recognizer.last_language, 'zh')

    def test_language_hint_maps_traditional_chinese_to_whisper_code(self):
        recognizer = self.recognizer('zh-TW')
        with patch.object(speech, 'traditional', side_effect=lambda text: text):
            recognizer.transcribe(struct.pack('<h', 100))
        self.assertEqual(recognizer.model.transcribe.call_args.kwargs['language'], 'zh')

    def test_silence_never_invokes_decoder(self):
        recognizer = self.recognizer()
        self.assertEqual(recognizer.transcribe(bytes(3200)), '')
        self.assertEqual(recognizer.transcribe(b''), '')
        recognizer.model.transcribe.assert_not_called()

    def test_invalid_and_broken_microphone_pcm_rejected(self):
        recognizer = self.recognizer()
        with self.assertRaises(ValueError):
            recognizer.transcribe(b'\x01')
        broken = struct.pack('<' + 'h' * 16, *([0] * 14 + [1000, -1000])) * 200
        with self.assertRaisesRegex(RuntimeError, 'periodic zero padding'):
            recognizer.transcribe(broken)
        recognizer.model.transcribe.assert_not_called()

    def test_factory_defaults_to_multilingual_whisper(self):
        with patch.object(speech, 'WhisperRecognizer') as whisper:
            speech.create_recognizer()
        whisper.assert_called_once_with('auto', 'small')
        with self.assertRaisesRegex(ValueError, 'Vosk requires'):
            speech.create_recognizer('auto', 'vosk')
        with self.assertRaisesRegex(ValueError, 'multilingual'):
            speech.WhisperRecognizer('auto', 'small.en')


if __name__ == '__main__':
    unittest.main()
