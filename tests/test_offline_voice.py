from array import array
import importlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
import wave
import subprocess
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
speech = importlib.import_module('offline_speech')
voice = importlib.import_module('voice_agent')
health = importlib.import_module('audio_health')


class OfflineVoiceTests(unittest.TestCase):
    def test_spoken_music_request_is_detected(self):
        self.assertEqual(voice.music_query('\u6211\u60F3\u807D\u591C\u4F86\u9999'), '\u591C\u4F86\u9999')
        self.assertEqual(voice.music_query('play song My Song'), 'My Song')
        self.assertIsNone(voice.music_query('\u4F60\u6709\u807D\u898B\u6211\u55CE'))

    def test_local_music_lookup_keeps_ambiguous_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('Night Song - A.mp3', 'Night Song - B.flac', 'unrelated.wav'):
                (root / name).touch()
            self.assertEqual(len(voice.find_local_music(root, 'Night Song')), 2)
            (root / 'Night Song.mp3').touch()
            self.assertEqual(voice.find_local_music(root, 'Night Song'), [root / 'Night Song.mp3'])
            self.assertEqual(voice.find_local_music(root, 'Missing'), [])

    def test_idle_auto_poll_does_not_repeat_listening_announcement(self):
        box = Mock()
        box.capture_speech.return_value = b''
        recognizer = Mock(language='zh')
        with patch('sys.stdout', io.StringIO()) as terminal:
            voice.listen_once(box, recognizer, automatic=True, announce=True)
            voice.listen_once(box, recognizer, automatic=True, announce=False)
        self.assertEqual(terminal.getvalue().count('Listening (zh)'), 1)
        box.display.assert_called_once()
        self.assertEqual(box.capture_speech.call_count, 2)

    def test_automatic_listening_uses_device_endpoint(self):
        box = Mock()
        box.capture_speech.return_value = struct.pack('<h', 200) * 16000
        recognizer = Mock(language='zh')
        recognizer.transcribe.return_value = '\u4F60\u597D'
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(voice.listen_once(box, recognizer, automatic=True), '\u4F60\u597D')
        box.capture_speech.assert_called_once_with(80, 1.0)
        box.capture.assert_not_called()

    def test_automatic_idle_does_not_run_recognition(self):
        box = Mock()
        box.capture_speech.return_value = b''
        recognizer = Mock(language='zh')
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(voice.listen_once(box, recognizer, automatic=True), '')
        recognizer.transcribe.assert_not_called()

    def test_piper_failure_includes_diagnostic_stderr(self):
        with patch.object(speech, 'model_path', return_value=Path('/tmp/voice.onnx')), \
             patch.object(speech.subprocess, 'run', side_effect=subprocess.CalledProcessError(
                 1, 'piper', stderr='Voice configuration could not be loaded')):
            with self.assertRaisesRegex(RuntimeError, 'Voice configuration could not be loaded'):
                speech.synthesize('hello', '/tmp/unused.wav', 'en')

    def test_periodic_padding_from_reported_recording_is_rejected(self):
        frame = [0] * 16
        frame[9], frame[10] = 1500, -1400
        pcm = struct.pack('<16h', *frame) * 1000
        self.assertTrue(health.has_periodic_zero_padding(pcm))
        with self.assertRaisesRegex(RuntimeError, 'slot32-v3'):
            health.require_valid_framing(pcm)

    def test_silence_and_contiguous_speech_are_not_padding(self):
        for pcm in (bytes(32000), struct.pack('<hhh', 1000, -1200, 0) * 6000):
            self.assertFalse(health.has_periodic_zero_padding(pcm))

    def test_quiet_contiguous_recording_reaches_recognizer(self):
        box = Mock()
        box.capture.return_value = struct.pack('<h', 100) * 16000
        recognizer = Mock(language='zh')
        recognizer.transcribe.return_value = '\u4F60\u597D'
        with tempfile.TemporaryDirectory() as temp, patch('sys.stdout', io.StringIO()) as terminal:
            path = Path(temp) / 'microphone.wav'
            self.assertEqual(voice.listen_once(box, recognizer, 4, path), '\u4F60\u597D')
            box.capture.assert_called_once_with(4)
            recognizer.transcribe.assert_called_once_with(box.capture.return_value)
            self.assertIn('mean=100.0, peak=100', terminal.getvalue())
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.readframes(16000), box.capture.return_value)

    def test_zero_microphone_signal_is_reported(self):
        box = Mock()
        box.capture.return_value = bytes(32000)
        recognizer = Mock(language='zh')
        with patch('sys.stdout', io.StringIO()) as terminal:
            self.assertEqual(voice.listen_once(box, recognizer), '')
        recognizer.transcribe.assert_not_called()
        self.assertIn('No microphone signal', terminal.getvalue())
        self.assertIn('No microphone signal', box.display.call_args.args[0])

    def test_empty_transcript_is_no_longer_silent(self):
        box = Mock()
        box.capture.return_value = struct.pack('<h', 1000) * 16000
        recognizer = Mock(language='en')
        recognizer.transcribe.return_value = ''
        with patch('sys.stdout', io.StringIO()) as terminal:
            self.assertEqual(voice.listen_once(box, recognizer), '')
        self.assertIn('No speech recognized. Selected model: en', terminal.getvalue())
        self.assertIn('No speech recognized', box.display.call_args.args[0])

    def test_user_and_reply_are_mirrored_with_roles(self):
        box = Mock()
        transcript = '\u4F60\u597D'
        reply = '\u4F60\u597D\U0001F916'
        terminal = io.StringIO()
        with patch('sys.stdout', terminal), patch.object(voice, 'synthesize') as synthesize:
            voice.show_user_message(box, transcript)
            voice.speak_reply(box, reply, '/tmp')
        self.assertIn('You: ' + transcript, terminal.getvalue())
        self.assertIn('Pi: ' + reply, terminal.getvalue())
        self.assertEqual(box.display.call_args_list[0].args,
                         ('You (1/1)\n' + transcript, 'zh-TW'))
        self.assertEqual(box.display.call_args_list[1].args,
                         ('Pi (1/1)\n' + reply, 'zh-TW'))
        synthesize.assert_called_once()
        box.play.assert_called_once()

    def test_listening_avatar_keeps_previous_dialogue_visible(self):
        box = Mock()
        box.status = 'BOX1 OK face=1'
        voice.show_status(box, 'listening', 'Listening now')
        box.expression.assert_called_once_with('listening')
        box.display.assert_not_called()

    def test_status_uses_text_on_older_firmware(self):
        box = Mock()
        box.status = 'BOX1 OK'
        voice.show_status(box, 'thinking', 'Recognizing...')
        box.display.assert_called_once_with('Recognizing...', 'en')
        box.expression.assert_not_called()

    def test_long_cjk_reply_is_paged_without_truncation(self):
        text = '\u4E2D\u6587\U0001F916' * 120
        pages = list(voice.conversation_pages(text, 'zh-TW'))
        self.assertGreater(len(pages), 1)
        self.assertEqual(''.join(pages).replace('\n', ''), text)
        self.assertTrue(all(len(page.split('\n')) <= 6 for page in pages))
        for page in pages:
            for line in page.split('\n'):
                self.assertLessEqual(sum(18 if ord(c) >= 0x1F000 else 16 for c in line), 208)
        self.assertTrue(all(len(page.encode()) + 50 < 1024 for page in pages))
        box = Mock()
        with patch('sys.stdout', io.StringIO()), patch.object(voice, 'synthesize') as synthesize:
            voice.speak_reply(box, text, '/tmp')
        self.assertEqual(box.display.call_count, len(pages))
        self.assertEqual(box.play.call_count, len(pages))
        self.assertEqual(synthesize.call_count, len(pages))
        self.assertTrue(box.display.call_args.args[0].endswith(pages[-1]))

    def test_english_words_survive_page_wrapping(self):
        text = 'Recognized speech and agent replies appear on both screens. ' * 30
        pages = list(voice.conversation_pages(text, 'en'))
        self.assertEqual(' '.join(' '.join(pages).split()), ' '.join(text.split()))

    def test_level_signed_boundary(self):
        self.assertEqual(voice.pcm_level(struct.pack('<hh', -32768, 32767)), 32767.5)
        self.assertEqual(voice.pcm_level(b''), 0)

    def test_vad_preroll_silence_and_reset(self):
        detector = voice.VoiceActivity(threshold=500, silence=0.5)
        quiet = b'\0' * 8000
        loud = struct.pack('<h', -2000) * 4000
        self.assertIsNone(detector.feed(quiet))
        self.assertIsNone(detector.feed(loud))
        self.assertIsNone(detector.feed(quiet))
        self.assertEqual(detector.feed(quiet), quiet + loud + quiet + quiet)
        self.assertIsNone(detector.feed(quiet))

    def test_vad_utterance_limit(self):
        detector = voice.VoiceActivity(threshold=500, maximum=0.5)
        loud = struct.pack('<h', 1000) * 4000
        self.assertIsNone(detector.feed(loud))
        self.assertEqual(detector.feed(loud), loud * 2)

    def test_utf8_byte_pages(self):
        text = '\U0001F916\u4E2D' * 200
        pages = list(voice.display_pages(text))
        self.assertEqual(''.join(pages), text)
        self.assertTrue(all(len(page.encode('utf-8')) <= 1024 for page in pages))

    def test_clean_spoken_text_preserves_punctuation(self):
        self.assertEqual(speech.clean_text('**Hello** [world](https://example.com) - 1+2! \U0001F916\n```code```'),
                         'Hello world - 1+2!')

    def test_recognizer_collects_segments_preserves_english_spaces(self):
        class FakeRecognizer:
            def __init__(self, *args): pass
            def AcceptWaveform(self, data): return True
            def Result(self): return json.dumps({'text': 'hello world'})
            def FinalResult(self): return json.dumps({'text': 'good day'})
        fake = types.SimpleNamespace(KaldiRecognizer=FakeRecognizer)
        recognizer = speech.Recognizer.__new__(speech.Recognizer)
        recognizer.model = object()
        recognizer.language = 'en'
        with patch.dict(sys.modules, vosk=fake):
            self.assertEqual(recognizer.transcribe(b'\0' * 8), 'hello world good day')
            recognizer.language = 'zh'
            with patch.object(speech, 'traditional', side_effect=lambda text: text) as convert:
                recognizer.transcribe(b'\0' * 8)
                convert.assert_called_once_with('helloworldgoodday')

    def test_pi_is_noninteractive_and_prompt_not_shell(self):
        with patch.object(voice.subprocess, 'run') as run:
            run.return_value.stdout = 'reply'
            self.assertEqual(voice.ask_pi('hello $(touch /tmp/unwanted)', '/tmp/session'), 'reply')
            argv = run.call_args.args[0]
            self.assertEqual(argv[:2], ['pi', '--print'])
            self.assertNotIn('--no-extensions', argv)
            self.assertIn('box3_*', argv[argv.index('--exclude-tools') + 1])
            self.assertEqual(argv[argv.index('--thinking') + 1], 'off')
            self.assertIn('$(touch /tmp/unwanted)', argv[-1])
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_pi_extension_discovery_can_be_disabled_for_diagnosis(self):
        with patch.object(voice.subprocess, 'run') as run:
            run.return_value.stdout = 'reply'
            voice.ask_pi('hello', '/tmp/session', no_extensions=True)
            self.assertIn('--no-extensions', run.call_args.args[0])

    def test_piper_uses_stdin_and_resamples(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / 'voice.onnx'
            model.touch()
            with patch.object(speech, 'model_path', return_value=model), \
                 patch.object(speech.subprocess, 'run') as run:
                speech.synthesize('hello "world" $(nothing)', Path(temp) / 'out.wav', 'en')
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args_list[0].kwargs['input'], 'hello "world" $(nothing)\n')
                self.assertEqual(run.call_args_list[1].args[0][0], 'ffmpeg')
                self.assertIn('16000', run.call_args_list[1].args[0])


if __name__ == '__main__':
    unittest.main()
