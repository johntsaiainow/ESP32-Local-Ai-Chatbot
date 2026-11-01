"""Wake gating tests do not need microphone hardware or downloaded models."""
import io
import queue
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from voice_agent import WakeWordGate, listen_once, show_wake_state, sync_wake_phrase
import voice_agent as voice


class WakeWordTests(unittest.TestCase):
    def test_pi_failure_keeps_no_ruview_conversation_open(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, queue.Empty, '/quit']
        box = Mock(status='BOX1 OK', synchronized=True)
        box.environment.return_value = (25, 60)
        with patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--port', '/dev/test', '--wake-word', 'Osiris']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), patch.object(voice, 'create_recognizer'), \
             patch.object(voice, 'PiRPC'), patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', side_effect=['講個笑話', '現在幾度']), \
             patch.object(voice, 'stream_reply', side_effect=RuntimeError('context limit')), \
             patch.object(voice, 'speak_reply') as speak, \
             patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
            voice.main()
        box.environment.assert_called_once()
        speak.assert_called_once()

    def test_five_minute_window_expires_and_reply_renews_it(self):
        now = [0]
        gate = WakeWordGate(clock=lambda: now[0], followup_timeout=300)
        gate.arm_followup()
        now[0] = 299
        self.assertFalse(gate.waiting)
        self.assertEqual(gate.accept('現在幾度'), '現在幾度')
        gate.arm_followup()
        now[0] = 598
        self.assertFalse(gate.waiting)
        now[0] = 599
        self.assertTrue(gate.waiting)

    def test_without_ruview_first_spoken_request_needs_no_wake_word(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, '/quit']
        box = Mock(status='BOX1 OK', synchronized=True)
        box.environment.return_value = (25, 60)
        with patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--port', '/dev/test', '--wake-word', 'Osiris']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), patch.object(voice, 'create_recognizer'), \
             patch.object(voice, 'PiRPC'), patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', return_value='現在幾度'), \
             patch.object(voice, 'speak_reply') as speak, patch('sys.stdout', io.StringIO()) as output:
            voice.main()
        box.environment.assert_called_once()
        speak.assert_called_once()
        self.assertIn('awake for 300s', output.getvalue())

    def test_osiris_chinese_transcriptions_wake_and_extract_request(self):
        for name in ('Osiris', 'osiris', '奧西里斯', '奥西里斯', '歐西里斯'):
            with self.subTest(name=name):
                gate = WakeWordGate('osiris')
                self.assertIsNone(gate.accept(name + '！'))
                self.assertFalse(gate.waiting)
                self.assertEqual(gate.accept('現在幾度？'), '現在幾度？')
                self.assertEqual(gate.accept(name + '，電量多少？'), '電量多少？')
        gate = WakeWordGate('Nova')
        self.assertIsNone(gate.accept('奧西里斯'))
        self.assertTrue(gate.waiting)

    def test_explicit_aliases_and_word_boundaries(self):
        gate = WakeWordGate('Osiris', aliases=('小歐',))
        self.assertEqual(gate.accept('小歐，溫度多少'), '溫度多少')
        self.assertIsNone(gate.accept('歐西里斯'))
        self.assertTrue(gate.waiting)
        self.assertIsNone(gate.accept('MyOsirisApp'))
        with self.assertRaises(ValueError):
            WakeWordGate(aliases=('bad\x00alias',))

    def test_device_phrase_update_clears_existing_followup(self):
        gate = WakeWordGate()
        gate.arm_followup()
        box = Mock()
        box.wake_phrase.return_value = 'Hey Nova'
        with patch('sys.stdout', io.StringIO()):
            self.assertTrue(sync_wake_phrase(box, gate))
        self.assertTrue(gate.waiting)
        self.assertIsNone(gate.accept('Osiris, hello'))
        self.assertEqual(gate.accept('HEY NOVA, hello'), 'hello')
        gate.arm_followup()
        self.assertFalse(sync_wake_phrase(box, gate))
        self.assertFalse(gate.waiting)

    def test_multilingual_and_bounded_custom_phrase(self):
        self.assertEqual(WakeWordGate('小智').accept('小智，你好'), '你好')
        self.assertEqual(WakeWordGate('ねえオシリス').accept('ねえオシリス！こんにちは'), 'こんにちは')
        for value in ('', '___', 'a' * 97, '小' * 33, 'hello\x00world'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                WakeWordGate(value)

    def setUp(self):
        self.now = 100.0
        self.gate = WakeWordGate(clock=lambda: self.now)

    def test_background_speech_is_ignored(self):
        self.assertIsNone(self.gate.accept('What is the weather?'))
        self.assertTrue(self.gate.waiting)

    def test_wake_and_request_in_same_utterance(self):
        self.assertEqual(self.gate.accept('Osiris! What is the weather?'), 'What is the weather?')
        self.assertTrue(self.gate.waiting)
        self.assertIsNone(self.gate.accept('And tomorrow?'))

    def test_standalone_wake_accepts_exactly_one_followup(self):
        self.assertIsNone(self.gate.accept('OSIRIS!'))
        self.assertFalse(self.gate.waiting)
        self.assertEqual(self.gate.accept('Tell me a story'), 'Tell me a story')
        self.assertIsNone(self.gate.accept('Another story'))

    def test_empty_audio_does_not_consume_wake(self):
        self.gate.accept('Osiris')
        self.assertIsNone(self.gate.accept(''))
        self.assertFalse(self.gate.waiting)

    def test_wake_expires(self):
        self.gate.accept('Osiris!')
        self.now += 15
        self.assertIsNone(self.gate.accept('Too late'))
        self.assertTrue(self.gate.waiting)

    def test_repeated_wake_refreshes_timeout(self):
        self.gate.accept('Osiris')
        self.now += 14
        self.gate.accept('Osiris!')
        self.now += 2
        self.assertEqual(self.gate.accept('hello'), 'hello')

    def test_completed_reply_opens_thirty_second_followup(self):
        self.gate.accept('Osiris, hello')
        self.now += 180  # Pi processing/playback must not consume the new window.
        self.gate.arm_followup()
        self.assertFalse(self.gate.waiting)
        self.now += 29
        self.assertEqual(self.gate.accept('And tomorrow?'), 'And tomorrow?')
        self.gate.arm_followup()
        self.now += 30
        self.assertIsNone(self.gate.accept('Too late'))
        self.assertTrue(self.gate.waiting)

    def test_followup_ui_displays_thirty_seconds_and_listening(self):
        self.gate.arm_followup()
        box = Mock()
        with patch('sys.stdout', io.StringIO()):
            show_wake_state(box, self.gate)
        self.assertIn('30 seconds', box.display.call_args.args[0])
        box.expression.assert_called_with('listening')

    def test_keyword_must_be_a_whole_word(self):
        for text in ('xOsiris hello', 'Osiris123 hello', 'Osiriss hello', 'Orsiris hello'):
            with self.subTest(text=text):
                self.assertIsNone(self.gate.accept(text))

    def test_cjk_request_and_punctuation(self):
        self.assertEqual(self.gate.accept('Osiris！請問現在幾點？'), '請問現在幾點？')

    def test_exclamation_is_optional_and_custom_phrase_supported(self):
        gate = WakeWordGate('Hey Osiris!', clock=lambda: self.now)
        self.assertEqual(gate.accept('hey osiris, hello'), 'hello')
        with self.assertRaises(ValueError):
            WakeWordGate('!!!')

    def test_explicit_reset_clears_wake(self):
        self.gate.accept('Osiris')
        self.gate.reset()
        self.assertTrue(self.gate.waiting)

    def test_waiting_and_awake_ui_are_visible(self):
        box = Mock()
        with patch('sys.stdout', io.StringIO()):
            self.assertTrue(show_wake_state(box, self.gate))
            self.assertIn('Osiris!', box.display.call_args.args[0])
            box.expression.assert_called_with('sleeping')
            self.gate.accept('Osiris')
            self.assertFalse(show_wake_state(box, self.gate))
            self.assertIn('Awake!', box.display.call_args.args[0])
            box.expression.assert_called_with('listening')

    def test_idle_wake_listening_preserves_wake_screen(self):
        box = Mock()
        box.capture_speech.return_value = b'\x10\x00' * 1600
        recognizer = Mock(language='auto')
        recognizer.transcribe.return_value = 'background conversation'
        with patch('sys.stdout', io.StringIO()):
            text = listen_once(box, recognizer, automatic=True, announce=False, wake_waiting=True)
        self.assertIsNone(self.gate.accept(text))
        box.display.assert_not_called()
        box.expression.assert_not_called()
