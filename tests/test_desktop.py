"""Desktop orchestration tests use fake audio/model backends, never a real microphone."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from desktop_core import DesktopAudio, DesktopEngine, Settings, Stopped, resample_pcm


class DesktopTests(unittest.TestCase):
    def test_native_rate_conversion_retains_duration_and_amplitude(self):
        import numpy as np
        pcm = np.full(4800, 1234, dtype=np.int16).tobytes()
        converted = np.frombuffer(resample_pcm(pcm, 48000, 16000), dtype=np.int16)
        self.assertEqual(len(converted), 1600)
        self.assertTrue((converted == 1234).all())

    def test_text_only_never_opens_audio_or_loads_speech(self):
        backend = Mock()
        audio_factory, recognizer_factory = Mock(), Mock()
        events = []
        engine = None
        def emit(kind, value):
            events.append((kind, value))
            if kind == 'ready':
                engine.submit('你好')
            if kind == 'complete':
                engine.stop()
        def ask(text, on_delta):
            on_delta('您好。')
            return '您好。'
        backend.ask.side_effect = ask
        engine = DesktopEngine(Settings(microphone=False, speech=False), emit,
                               backend_factory=lambda cfg, temp: backend,
                               audio_factory=audio_factory, recognizer_factory=recognizer_factory)
        with patch('desktop_core.warmup_resident') as warmup:
            engine.run()
        audio_factory.assert_not_called()
        recognizer_factory.assert_not_called()
        warmup.assert_not_called()
        self.assertIn(('delta', '您好。'), events)
        self.assertIn(('user', '你好'), events)
        backend.close.assert_called_once()

    def test_wake_speech_and_followup_use_local_capture(self):
        backend = Mock()
        transcript = iter(['background', 'Osiris', 'Hello'])
        recognizer = Mock()
        recognizer.transcribe.side_effect = lambda pcm: next(transcript)
        audio = Mock()
        audio.capture.return_value = b'\x01\x00' * 100
        events = []
        engine = None
        def emit(kind, value):
            events.append((kind, value))
            if kind == 'complete':
                engine.stop()
        backend.ask.side_effect = lambda text, on_delta: (on_delta('Hi!') or 'Hi!')
        engine = DesktopEngine(Settings(speech=False), emit,
                               backend_factory=lambda cfg, temp: backend,
                               audio_factory=lambda *args: audio,
                               recognizer_factory=lambda *args: recognizer)
        engine.run()
        self.assertEqual([value for kind,value in events if kind == 'user'], ['Hello'])
        self.assertIn(('state', 'sleeping'), events)
        self.assertIn(('state', 'listening'), events)
        self.assertFalse(engine.gate.waiting)
        self.assertGreater(engine.gate.remaining, 29)

    def test_followup_starts_after_audio_finishes(self):
        engine = DesktopEngine(Settings(), lambda *args: None)
        engine.backend = Mock()
        now = [10.0]
        engine.gate.clock = lambda: now[0]
        def playback(*args):
            self.assertTrue(engine.gate.waiting)
            now[0] += 12
        with patch('desktop_core.stream_reply', side_effect=playback):
            engine.turn('Hello', Mock(), '/tmp')
        self.assertEqual(engine.gate.deadline, 52)

    def test_stop_cancels_active_backend_and_no_next_turn(self):
        backend = Mock()
        entered = threading.Event()
        cancelled = threading.Event()
        backend.cancel.side_effect = cancelled.set
        def ask(text, on_delta):
            entered.set()
            self.assertTrue(cancelled.wait(2))
            on_delta('late')
        backend.ask.side_effect = ask
        events = []
        engine = DesktopEngine(Settings(microphone=False, speech=False),
                               lambda kind, value: events.append((kind,value)),
                               backend_factory=lambda *args: backend)
        engine.submit('Hello')
        thread = threading.Thread(target=engine.run)
        thread.start()
        self.assertTrue(entered.wait(2))
        engine.stop()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertNotIn(('delta', 'late'), events)
        self.assertNotIn(('complete', ''), events)
        backend.close.assert_called_once()

    def test_pending_keyboard_message_prevents_microphone_read(self):
        settings = Settings()
        with patch.dict(sys.modules, {'sounddevice': Mock()}):
            audio = DesktopAudio(settings, threading.Event(), lambda *args: None)
        audio.sd.query_devices.return_value = {'default_samplerate': 48000}
        import queue
        pending = queue.Queue()
        pending.put('hello')
        self.assertIsNone(audio.capture(pending, lambda: None))
        audio.sd.RawInputStream.assert_not_called()

    def test_invalid_phrase_and_bounded_input(self):
        with self.assertRaises(ValueError):
            DesktopEngine(Settings(wake_phrase=''), Mock())
        engine = DesktopEngine(Settings(), Mock())
        for text in ('', '中' * 3000):
            with self.assertRaises(ValueError):
                engine.submit(text)
        engine.submit('one')
        with self.assertRaises(ValueError):
            engine.submit('two')


try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QSettings
    from desktop_osiris import OsirisWindow
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'Install requirements-desktop.txt for Qt tests')
class DesktopGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def test_original_emoji_streamed_text_and_saved_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = QSettings(str(Path(directory) / 'desktop.ini'), QSettings.Format.IniFormat)
            with patch('desktop_osiris.OsirisWindow.refresh_devices'):
                window = OsirisWindow(store)
            self.assertFalse(window.avatar.pixmap().isNull())
            for state in ('happy','sleeping','speaking','thinking','error','listening'):
                window.show_state(state)
                self.assertFalse(window.avatar.pixmap().isNull())
            window.handle_event('user', '你好')
            window.handle_event('delta', '您好')
            window.handle_event('delta', '。')
            self.assertIn('Osiris: 您好。', window.chat.toPlainText())
            store.setValue('wake_phrase', 'Hey Nova')
            window.close()
            with patch('desktop_osiris.OsirisWindow.refresh_devices'):
                restored = OsirisWindow(store)
            self.assertEqual(restored.configuration().wake_phrase, 'Hey Nova')
            restored.close()

    def test_real_qthread_text_turn_and_clean_close(self):
        from desktop_osiris import EngineThread
        backend = Mock()
        backend.ask.side_effect = lambda text, on_delta: (on_delta('Hello!') or 'Hello!')
        def factory(cfg, parent):
            worker = EngineThread(cfg, parent)
            worker.engine.backend_factory = lambda *args: backend
            return worker
        with tempfile.TemporaryDirectory() as directory:
            store = QSettings(str(Path(directory) / 'desktop.ini'), QSettings.Format.IniFormat)
            with patch('desktop_osiris.OsirisWindow.refresh_devices'):
                window = OsirisWindow(store, factory)
            window.microphone.setChecked(False)
            window.speech.setChecked(False)
            window.start()
            deadline = time.monotonic() + 3
            while not window.send_button.isEnabled() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(window.send_button.isEnabled())
            window.message.setText('Hi')
            window.send()
            while 'Hello!' not in window.chat.toPlainText() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIn('Hello!', window.chat.toPlainText())
            window.close()
            while window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIsNone(window.worker)
            backend.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
