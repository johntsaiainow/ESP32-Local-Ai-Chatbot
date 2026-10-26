from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from emotion_runtime import EMOTIONS, EmotionDecoder, EmotionBackend
from box3 import Box3
from chat_backends import CloudChat


class EmotionRuntimeTests(unittest.TestCase):
    def test_all_markers_in_split_chunks_and_strip_body_emoji(self):
        for emoji, name in EMOTIONS.items():
            for size in (1, 2, 4, 64):
                decoder = EmotionDecoder()
                raw = emoji + '\ufe0f\r\n你好🙂，測試👨‍👩‍👦。'
                collected = ''.join(decoder.feed(raw[i:i+size]) for i in range(0, len(raw), size))
                self.assertEqual(decoder.emotion, name)
                self.assertEqual(decoder.finish(), '你好，測試。')
                self.assertEqual(collected, decoder.text)

    def test_invalid_prefix_never_delivers_speech(self):
        for raw in ('Hello\nWorld', '🙂🙂\nHello', 'x' * 17):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                EmotionDecoder().feed(raw)
        for raw in ('🙂', '🙂\n😎'):
            decoder = EmotionDecoder()
            self.assertEqual(decoder.feed(raw), '')
            with self.assertRaises(ValueError):
                decoder.finish()

    def test_streaming_and_nonstreaming_backend(self):
        class Backend:
            emotion_mode = False
            def ask(self, text, on_delta=None):
                if on_delta:
                    for part in ('🤔', '\n', '你好', '😎', '。'):
                        on_delta(part)
                return '🤔\n你好😎。'
        for streaming in (False, True):
            backend = Backend()
            wrapper = EmotionBackend(backend)
            received = []
            self.assertEqual(wrapper.ask('Hello', received.append if streaming else None), '你好。')
            self.assertEqual(wrapper.emotion_expression, 'mood_thinking')
            self.assertTrue(backend.emotion_mode)
            if streaming:
                self.assertEqual(''.join(received), '你好。')

    def test_device_expression_compatibility(self):
        device = Box3.__new__(Box3)
        device.command = Mock()
        for fields, expected in [('face=1 emojistates=1 moods=1', 'mood_happy'),
                                 ('face=1 emojistates=1', 'speaking')]:
            device.status = 'BOX1 OK ' + fields
            device.expression('mood_happy')
            device.command.assert_called_with('FACE ' + expected)

    def test_cloud_prompt_can_switch_back_to_legacy(self):
        # Build only the instruction provider; no credentials or HTTP requests.
        client = CloudChat.__new__(CloudChat)
        client.emotion_mode = True
        self.assertIn('one emoji', client.instructions())
        self.assertNotIn('without markdown or emoji', client.instructions(True))
        client.emotion_mode = False
        self.assertNotIn('one emoji', client.instructions())
        self.assertIn('without markdown or emoji', client.instructions(True))

    def test_rejected_reply_restores_cloud_history(self):
        class Backend:
            emotion_mode = False
            history = [{'role': 'user', 'content': 'Previous'}]
            def ask(self, prompt):
                self.history = self.history + [{'role': 'assistant', 'content': 'Invalid reply'}]
                return 'Invalid reply'
        backend = Backend()
        with self.assertRaises(ValueError):
            EmotionBackend(backend).ask('Hello')
        self.assertEqual(backend.history, [{'role': 'user', 'content': 'Previous'}])

    def test_streaming_pipeline_only_synthesizes_clean_text_and_displays_mood(self):
        import tempfile
        from unittest.mock import patch
        import streaming_reply
        class Backend:
            def ask(self, prompt, on_delta):
                for part in ('😔', '\n', '我理解', '🙂', '你的感受。'):
                    on_delta(part)
                return '😔\n我理解🙂你的感受。'
        device = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.object(streaming_reply, 'synthesize_resident') as synthesize:
            result = streaming_reply.stream_reply(device, EmotionBackend(Backend()), '你好', temp,
                                                  'Test', lambda text: 'zh', lambda text, lang: [text])
        self.assertEqual(result, '我理解你的感受。')
        synthesize.assert_called_once()
        self.assertEqual(synthesize.call_args.args[0], '我理解你的感受。')
        device.expression.assert_called_once_with('mood_sad')


if __name__ == '__main__':
    unittest.main()
