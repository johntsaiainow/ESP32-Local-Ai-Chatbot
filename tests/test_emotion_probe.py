import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from emotion_probe import split_reply, EMOTIONS, ALL_CASES, StreamMetrics


class EmotionProbeTests(unittest.TestCase):
    def test_every_marker_and_variation_selector(self):
        self.assertEqual(len(ALL_CASES), 21)
        for emoji, name in EMOTIONS.items():
            self.assertEqual(split_reply(emoji + '\ufe0f\n測試。')[0]['emotion'], name)

    def test_stream_prefix_across_chunks(self):
        now = [0]
        tracker = StreamMetrics(lambda: now[0])
        for stamp, delta in ((0.1, '🤔'), (0.2, '\n'), (0.3, '讓我'), (0.4, '想想。')):
            now[0] = stamp
            tracker.feed(delta)
        now[0] = 0.5
        result = tracker.finish()
        self.assertEqual(result['first_delta_ms'], 100)
        self.assertEqual(result['emoji_visible_ms'], 100)
        self.assertEqual(result['emoji_delimited_ms'], 200)
        self.assertEqual(result['first_spoken_text_ms'], 300)
        self.assertEqual(result['first_sentence_ms'], 400)
        self.assertEqual(result['complete_ms'], 500)
        self.assertEqual(result['text_chunks'], 4)

    def test_separates_event_from_speech(self):
        event, spoken = split_reply('🤔\n讓我想想。')
        self.assertEqual(event, {'type': 'llm', 'text': '🤔', 'emotion': 'thinking'})
        self.assertEqual(spoken, '讓我想想。')

    def test_rejects_unusable_or_leaking_output(self):
        for raw in ('Hello', '🙂', '🙂 Hello', 'invalid\nHello',
                    '🙂\nHello 😍', '🙂🙂\nHello', '🙂\nHello 👨‍👩‍👦'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                split_reply(raw)


if __name__ == '__main__':
    unittest.main()
