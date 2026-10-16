"""Offline multilingual speech recognition with Whisper, optional Vosk, and Piper."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
import wave
import threading
import time
from audio_health import require_valid_framing

MODELS = Path(os.environ.get('BOX3_MODELS_DIR', '~/aion-voice/models')).expanduser()


def model_path(kind, language):
    if language not in ('en', 'zh', 'zh-TW'):
        raise ValueError('Offline speech supports en, zh, or zh-TW')
    chinese = language.startswith('zh')
    key = ('ZH' if chinese else 'EN')
    defaults = {'VOSK': 'vosk-cn' if chinese else 'vosk-en',
                'PIPER': 'zh_TW-huayan-medium.onnx' if chinese else 'en_US-lessac-medium.onnx'}
    path = Path(os.environ.get(f'BOX3_{kind}_{key}', str(MODELS / defaults[kind]))).expanduser()
    if kind == 'VOSK' and language == 'en' and not path.exists() and not os.environ.get('BOX3_VOSK_EN'):
        cached = Path(__file__).resolve().parents[1] / '.cache/voice-models/vosk-model-small-en-us-0.15'
        if cached.is_dir():
            path = cached
    if not path.exists():
        raise FileNotFoundError(f'{kind} model missing: {path}. Set BOX3_{kind}_{key}.')
    return path


def clean_text(text):
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_`#]', '', text)
    # Emoji remain on the display but are omitted from spoken output.
    text = re.sub(r'[\U0001F000-\U0001FAFF\uFE0E\uFE0F\u2705\u274C\u2764\u26A0]', '', text)
    return text.strip()


def traditional(text):
    from opencc import OpenCC
    return OpenCC('s2twp').convert(text)


class Recognizer:
    def __init__(self, language):
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        self.language = language
        self.model = Model(str(model_path('VOSK', language)))

    def transcribe(self, pcm):
        require_valid_framing(pcm)
        from vosk import KaldiRecognizer
        recognizer = KaldiRecognizer(self.model, 16000)
        segments = []
        for offset in range(0, len(pcm), 8000):
            if recognizer.AcceptWaveform(pcm[offset:offset + 8000]):
                segments.append(json.loads(recognizer.Result()).get('text', ''))
        segments.append(json.loads(recognizer.FinalResult()).get('text', ''))
        text = ' '.join(part for part in segments if part).strip()
        if self.language.startswith('zh'):
            return traditional(text.replace(' ', ''))
        return text  # Preserve spaces between English words.


class WhisperRecognizer:
    """Keep one multilingual model loaded for the entire voice session."""
    beam_size = 1
    def __init__(self, language='auto', model='small'):
        if language not in ('auto', 'en', 'zh', 'zh-TW'):
            raise ValueError('Whisper language must be auto, en, zh, or zh-TW')
        if model.endswith('.en'):
            raise ValueError('Choose a multilingual Whisper model, such as small (without .en)')
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError('Install Whisper with: host/.venv/bin/python -m pip install '
                               '-r host/requirements-offline.txt') from exc
        self.language = language
        self.last_language = None
        self.beam_size = 1
        cache = Path(__file__).resolve().parents[1] / '.cache/voice-models/whisper'
        print(f'Loading Whisper {model} (CPU int8, language={language})...', file=sys.stderr, flush=True)
        from faster_whisper.utils import download_model
        from huggingface_hub.errors import LocalEntryNotFoundError
        if Path(model).expanduser().is_dir():
            resolved = str(Path(model).expanduser())
        else:
            try:
                resolved = download_model(model, cache_dir=str(cache), local_files_only=True)
            except LocalEntryNotFoundError:
                print('Downloading Whisper model; subsequent runs use the local cache.',
                      file=sys.stderr, flush=True)
                resolved = download_model(model, cache_dir=str(cache))
        self.model = WhisperModel(resolved, device='cpu', compute_type='int8', cpu_threads=4)
        if not self.model.model.is_multilingual:
            raise ValueError('The selected Whisper model is English-only; choose a multilingual model')

    def transcribe(self, pcm):
        if len(pcm) % 2:
            raise ValueError('Whisper input must contain complete PCM16 samples')
        require_valid_framing(pcm)
        if not pcm or not any(pcm):
            return ''
        import numpy as np
        audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        language = None if self.language == 'auto' else self.language.split('-')[0]
        segments, info = self.model.transcribe(
            audio, language=language, task='transcribe', beam_size=self.beam_size,
            temperature=0, condition_on_previous_text=False, vad_filter=True,
            initial_prompt='Mandarin Chinese and English conversation.')
        self.last_language = info.language
        # Do not strip internal spaces: English words may appear inside Chinese.
        text = ' '.join(segment.text.strip() for segment in segments if segment.text.strip())
        return traditional(text).strip()


def create_recognizer(language='auto', backend='whisper', model='small'):
    if backend == 'whisper':
        return WhisperRecognizer(language, model)
    if backend == 'vosk':
        if language == 'auto':
            raise ValueError('Vosk requires --language zh or --language en; use Whisper for auto')
        return Recognizer(language)
    raise ValueError('Unknown recognition backend: ' + backend)


def transcribe_file(path, language='auto', backend='whisper', model='small'):
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('Speech input must be mono PCM16 WAV at 16000 Hz')
        pcm = wav.readframes(wav.getnframes())
    return create_recognizer(language, backend, model).transcribe(pcm)


def convert_audio(source, destination):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source),
                    '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(destination)],
                   check=True, capture_output=True, timeout=120)


def render_music(source, destination, backend='mpv'):
    if backend == 'ffmpeg':
        return convert_audio(source, destination)
    # Reuse the installed player as a decoder. PCM file output routes audio to
    # BOX-3 rather than opening the host's default sound device or IPC player.
    try:
        subprocess.run(['mpv', '--no-config', '--load-scripts=no', '--no-video',
                        '--input-terminal=no', '--really-quiet', '--ao=pcm',
                        f'--ao-pcm-file={destination}', '--ao-pcm-waveheader=yes',
                        '--audio-samplerate=16000', '--audio-channels=mono',
                        '--audio-format=s16', '--', str(source)],
                       check=True, capture_output=True, text=True, timeout=180)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'mpv decoding failed: {(exc.stderr or str(exc))[-2000:]}') from exc


def speech_segments(text, fallback='en'):
    """Keep spaces, punctuation, and numbers while grouping Chinese/Latin runs."""
    segments = []
    current = None
    buffer = ''
    for character in text:
        code = ord(character)
        if 0x3400 <= code <= 0x9FFF or 0x20000 <= code <= 0x323AF:
            selected = 'zh-TW'
        elif character.isalpha() and 'LATIN' in unicodedata.name(character, ''):
            selected = 'en'
        else:
            selected = None
        if selected is not None:
            if current is not None and current != selected:
                segments.append((current, buffer))
                buffer = ''
            current = selected
        buffer += character
    if buffer:
        segments.append((current or fallback, buffer))
    return segments


def synthesize(text, output, language):
    text = clean_text(text)
    segments = speech_segments(text, language)
    if len(segments) <= 1:
        selected, content = segments[0] if segments else (language, '')
        return _synthesize_single(content, output, selected)
    # Render every language run before playback, then join PCM without WAV headers.
    with tempfile.TemporaryDirectory(prefix='box3-bilingual-') as temp:
        rendered = []
        for index, (selected, content) in enumerate(segments):
            path = Path(temp) / f'{index}.wav'
            _synthesize_single(content, path, selected)
            rendered.append(path)
        with wave.open(str(output), 'wb') as destination:
            destination.setnchannels(1)
            destination.setsampwidth(2)
            destination.setframerate(16000)
            for path in rendered:
                with wave.open(str(path), 'rb') as source:
                    if (source.getnchannels(), source.getsampwidth(), source.getframerate(),
                        source.getcomptype()) != (1, 2, 16000, 'NONE'):
                        raise ValueError('Synthesized segments must be mono PCM16 at 16000 Hz')
                    while True:
                        pcm = source.readframes(16000)
                        if not pcm:
                            break
                        destination.writeframes(pcm)


def _synthesize_single(text, output, language):
    text = clean_text(text)
    if not text:
        # A valid empty wave allows an emoji-only reply to display silently.
        with wave.open(str(output), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
        return
    model = model_path('PIPER', language)
    with tempfile.TemporaryDirectory(prefix='box3-piper-') as temp:
        source = Path(temp) / 'piper.wav'
        try:
            subprocess.run([sys.executable, '-m', 'piper', '--model', str(model),
                            '--output_file', str(source)], input=text + '\n', text=True,
                           encoding='utf-8', check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f'Piper synthesis failed: {(exc.stderr or str(exc))[-2000:]}') from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Piper synthesis exceeded 120 seconds; check host CPU/model configuration') from exc
        convert_audio(source, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    stt = sub.add_parser('stt')
    stt.add_argument('--input', required=True, type=Path)
    stt.add_argument('--language', choices=('auto', 'en', 'zh', 'zh-TW'), default='auto')
    stt.add_argument('--backend', choices=('whisper', 'vosk'), default='whisper')
    stt.add_argument('--model', default=os.environ.get('BOX3_WHISPER_MODEL', 'small'))
    tts = sub.add_parser('tts')
    tts.add_argument('--text-file', required=True, type=Path)
    tts.add_argument('--output', required=True, type=Path)
    tts.add_argument('--language', choices=('en', 'zh', 'zh-TW'), required=True)
    args = parser.parse_args()
    if args.action == 'stt':
        print(transcribe_file(args.input, args.language, args.backend, args.model))
    else:
        synthesize(args.text_file.read_text(encoding='utf-8'), args.output, args.language)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Offline speech: {exc}', file=sys.stderr)
        sys.exit(1)


_piper_voices = {}
_piper_lock = threading.Lock()


def _resident_voice(model, language):
    from piper import PiperVoice
    key = str(model)
    if key not in _piper_voices:
        started = time.monotonic()
        _piper_voices[key] = PiperVoice.load(key)
        print(f'LATENCY stage=tts_model_load language={language} elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
    return _piper_voices[key]


def warmup_resident(languages):
    """Move configured voice loading to startup without generating or playing audio."""
    with _piper_lock:
        for language in languages:
            try:
                model = model_path('PIPER', language)
            except FileNotFoundError:
                print(f'TTS warmup: no configured voice for {language}; skipped.', file=sys.stderr)
                continue
            _resident_voice(model, language)


def synthesize_resident(text, output, language):
    """Keep Piper voices loaded between sentences/turns; one synthesis worker owns them."""
    text = clean_text(text)
    segments = speech_segments(text, language)
    with _piper_lock, tempfile.TemporaryDirectory(prefix='osiris-piper-') as temp:
        with wave.open(str(output), 'wb') as destination:
            destination.setnchannels(1)
            destination.setsampwidth(2)
            destination.setframerate(16000)
            for index, (selected, content) in enumerate(segments):
                model = model_path('PIPER', selected)
                voice = _resident_voice(model, selected)
                source = Path(temp)/f'{index}.wav'
                with wave.open(str(source), 'wb') as wav:
                    voice.synthesize_wav(content, wav)
                with wave.open(str(source), 'rb') as wav:
                    if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 8000 <= wav.getframerate() <= 48000:
                        raise ValueError('Piper must return mono PCM16 at 8–48 kHz')
                    pcm = wav.readframes(wav.getnframes())
                    rate = wav.getframerate()
                if rate != 16000 and pcm:
                    import numpy as np
                    samples = np.frombuffer(pcm, dtype='<i2')
                    positions = np.arange(len(samples)*16000//rate, dtype=np.float64)*rate/16000
                    pcm = np.interp(positions, np.arange(len(samples)), samples).clip(-32768, 32767).astype('<i2').tobytes()
                destination.writeframes(pcm)
