"""Desktop Osiris engine. No serial ports, ESP32, or Qt dependencies."""
from dataclasses import dataclass
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import wave

from chat_backends import CloudChat
from offline_speech import create_recognizer, warmup_resident
from pi_rpc import PiRPC
from streaming_reply import stream_reply
from voice_agent import VoiceActivity, WakeWordGate, reply_language


class Stopped(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    provider: str = 'pi'
    model: str = ''
    wake_phrase: str = 'Osiris'
    language: str = 'auto'
    whisper_model: str = 'small'
    microphone: bool = True
    speech: bool = True
    input_device: int | None = None
    output_device: int | None = None
    threshold: int = 500
    silence: float = 0.6


def resample_pcm(pcm, source_rate, target_rate):
    """Convert native-endian PCM16 mono; Whisper expects little-endian 16 kHz."""
    import numpy as np
    samples = np.frombuffer(pcm, dtype=np.int16)
    if source_rate != target_rate and len(samples):
        count = round(len(samples) * target_rate / source_rate)
        samples = np.interp(np.arange(count) * source_rate / target_rate,
                            np.arange(len(samples)), samples).astype(np.int16)
    return samples.tobytes()


class DesktopAudio:
    def __init__(self, settings, stop, emit):
        import sounddevice as sd
        self.sd, self.settings, self.stop, self.emit = sd, settings, stop, emit

    def capture(self, pending, idle):
        if self.stop.is_set() or not pending.empty():
            return None
        cfg = self.settings
        rate = round(self.sd.query_devices(cfg.input_device, 'input')['default_samplerate'])
        frames = max(1, round(rate / 10))
        vad = VoiceActivity(cfg.threshold, cfg.silence, maximum=15)
        with self.sd.RawInputStream(samplerate=rate, channels=1, dtype='int16',
                                    device=cfg.input_device, blocksize=frames) as mic:
            while not self.stop.is_set() and pending.empty():
                data, overflow = mic.read(frames)
                if overflow:
                    raise RuntimeError('Microphone overflow. Try a different audio device.')
                pcm = resample_pcm(bytes(data), rate, 16000)
                if sys.byteorder != 'little':
                    import numpy as np
                    pcm = np.frombuffer(pcm, dtype=np.int16).astype('<i2').tobytes()
                idle()
                utterance = vad.feed(pcm)
                if utterance is not None:
                    return utterance
        return None

    def expression(self, state):
        if self.stop.is_set():
            raise Stopped()
        self.emit('state', state)

    def display(self, text, language):
        pass  # Full streamed text is shown by the GUI, without device page limits.

    def play(self, path, progress=None):
        cfg = self.settings
        rate = round(self.sd.query_devices(cfg.output_device, 'output')['default_samplerate'])
        with wave.open(str(path), 'rb') as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError('Expected mono PCM16 speech')
            source_rate = wav.getframerate()
            with self.sd.RawOutputStream(samplerate=rate, channels=1, dtype='int16',
                                         device=cfg.output_device) as speaker:
                while True:
                    if self.stop.is_set():
                        speaker.abort()
                        raise Stopped()
                    data = wav.readframes(max(1, source_rate // 10))
                    if not data:
                        break
                    if sys.byteorder != 'little':
                        import numpy as np
                        data = np.frombuffer(data, dtype='<i2').astype(np.int16).tobytes()
                    if speaker.write(resample_pcm(data, source_rate, rate)):
                        self.emit('info', 'Speaker underrun: check system audio load.')


def desktop_prompt(text):
    return ('You are Osiris, a desktop voice assistant. Reply in under 50 words, '
            'starting with a short complete sentence. Use Traditional Chinese for Chinese '
            'requests; otherwise use English. Avoid markdown. Use tools only as needed; '
            'fetch current information for time-sensitive questions. Never invent live facts. '
            'Do not access ESP32 hardware. User request:\n' + text)


def make_backend(cfg, temp):
    if cfg.provider != 'pi':
        return CloudChat(cfg.provider, cfg.model or None)
    argv = ['pi', '--mode', 'rpc', '--thinking', 'off', '--exclude-tools',
            'box3_*,get_room_temperature,jukebox_control', '--session',
            str(Path(temp) / 'pi-session.jsonl')]
    return PiRPC(argv, prompt_builder=desktop_prompt)


class DesktopEngine:
    """Single audio owner; UI calls submit/stop, all heavy work stays in run()."""
    def __init__(self, cfg, emit, backend_factory=make_backend,
                 audio_factory=DesktopAudio, recognizer_factory=create_recognizer):
        self.cfg, self.emit = cfg, emit
        self.backend_factory, self.audio_factory = backend_factory, audio_factory
        self.recognizer_factory = recognizer_factory
        self.stopping = threading.Event()
        self.pending = queue.Queue(maxsize=1)
        self.backend = None
        self.gate = WakeWordGate(cfg.wake_phrase)
        self.last_idle = None

    def submit(self, text):
        text = text.strip()
        if not text or len(text.encode('utf-8')) > 8192:
            raise ValueError('Enter a message of up to 8192 UTF-8 bytes.')
        try:
            self.pending.put_nowait(text)
        except queue.Full:
            raise ValueError('A message is already waiting.') from None

    def stop(self):
        self.stopping.set()
        if self.backend is not None:
            self.backend.cancel()

    def check_stop(self):
        if self.stopping.is_set():
            raise Stopped()

    def idle(self):
        waiting = self.gate.waiting
        state = 'sleeping' if waiting else 'listening'
        if state != self.last_idle:
            self.emit('state', state)
            self.emit('info', f'Say “{self.gate.keyword}” to wake me.' if waiting else
                      'Awake — speak your request.')
            self.last_idle = state
        self.emit('countdown', '' if waiting else str(round(self.gate.remaining)))

    def ask(self, text, on_delta=None):
        """Observe backend streaming without coupling model code to Qt."""
        def delta(part):
            self.check_stop()
            self.emit('delta', part)
            if on_delta:
                on_delta(part)
        result = self.backend.ask(text, on_delta=delta)
        self.check_stop()
        return result

    def cancel(self):
        self.backend.cancel()

    def turn(self, text, audio, temp):
        self.check_stop()
        started = time.monotonic()
        self.emit('user', text)
        self.emit('state', 'thinking')
        if self.cfg.speech:
            stream_reply(audio, self, text, temp, 'Osiris', reply_language,
                         lambda sentence, language: [sentence])
        else:
            self.ask(text)
        self.check_stop()
        self.emit('info', f'Reply complete ({time.monotonic() - started:.1f}s).')
        self.emit('complete', '')
        self.gate.arm_followup()  # Start 30 seconds only after final speaker playback.
        self.last_idle = None

    def run(self):
        try:
            with tempfile.TemporaryDirectory(prefix='osiris-desktop-') as temp:
                self.emit('state', 'waiting')
                self.emit('info', 'Preparing Osiris…')
                self.backend = self.backend_factory(self.cfg, temp)
                self.check_stop()
                start = getattr(self.backend, 'start', None)
                if start:
                    start()
                self.check_stop()
                audio = self.audio_factory(self.cfg, self.stopping, self.emit) if (
                    self.cfg.microphone or self.cfg.speech) else None
                recognizer = None
                if self.cfg.microphone:
                    self.emit('info', 'Loading speech recognition…')
                    recognizer = self.recognizer_factory(self.cfg.language, 'whisper', self.cfg.whisper_model)
                if self.cfg.speech:
                    warmup_resident(['zh-TW', 'en'])
                self.check_stop()
                self.emit('ready', '')
                while not self.stopping.is_set():
                    self.idle()
                    try:
                        text = self.pending.get(timeout=0.1 if not recognizer else 0)
                    except queue.Empty:
                        if recognizer is None:
                            continue
                        pcm = audio.capture(self.pending, self.idle)
                        self.check_stop()
                        if not pcm:
                            continue
                        stamp = time.monotonic()
                        self.emit('state', 'thinking')
                        recognized = recognizer.transcribe(pcm)
                        self.check_stop()
                        self.emit('heard', recognized)
                        self.emit('info', f'Recognition: {time.monotonic()-stamp:.1f}s')
                        self.last_idle = None
                        text = self.gate.accept(recognized)
                        if not text:
                            continue
                    try:
                        self.turn(text, audio, temp)
                    except Stopped:
                        raise
                    except Exception as exc:
                        self.emit('error', str(exc))
                        self.gate.arm_followup()
                        self.last_idle = None
        except Stopped:
            pass
        except Exception as exc:
            if not self.stopping.is_set():
                self.emit('error', str(exc))
        finally:
            try:
                if self.backend is not None:
                    self.backend.close()
            except Exception as exc:
                self.emit('error', str(exc))
            finally:
                self.emit('finished', '')
