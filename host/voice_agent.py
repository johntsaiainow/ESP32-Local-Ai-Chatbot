"""Offline voice and keyboard interface between Pi CLI and ESP-BOX-3 over USB or Wi-Fi."""
import argparse
from array import array
from collections import deque
from contextlib import ExitStack
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave

from box3 import Box3, Box3Connection
from chat_backends import CloudChat
from streaming_reply import stream_reply
from emotion_runtime import EmotionBackend
from pi_stream import stream_pi
from ruview_presence import RuViewPresence, saved_configuration
from pi_rpc import PiRPC
from offline_speech import create_recognizer, render_music, synthesize, warmup_resident


class WakeWordGate:
    """Gate recognized speech; a standalone wake phrase arms one next request."""
    def __init__(self, keyword='Osiris', timeout=15, clock=time.monotonic, followup_timeout=30):
        self.timeout = timeout
        self.followup_timeout = followup_timeout
        self.clock = clock
        self.set_keyword(keyword)

    def set_keyword(self, keyword):
        keyword = keyword.strip(' \t\r\n!！.。,，?？:：;；')
        if not keyword or not any(ch.isalnum() or ord(ch) >= 128 for ch in keyword) or len(keyword.encode('utf-8')) > 96 or any(
                ord(ch) < 32 or ord(ch) == 127 for ch in keyword):
            raise ValueError('Wake phrase must contain text and fit within 96 UTF-8 bytes')
        self.keyword = keyword
        self.pattern = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(keyword) +
                                  r'(?![A-Za-z0-9_])', re.IGNORECASE)
        self.reset()

    def reset(self):
        self.deadline = None

    def arm_presence(self):
        """Accept a spoken request after a presence arrival."""
        if self.waiting:
            self.deadline = self.clock() + self.timeout

    def arm_followup(self):
        """Start a fresh listening window after the response finishes playing."""
        self.deadline = self.clock() + self.followup_timeout

    @property
    def remaining(self):
        return 0 if self.waiting else max(0, self.deadline - self.clock())

    @property
    def waiting(self):
        if self.deadline is not None and self.clock() >= self.deadline:
            self.reset()
        return self.deadline is None

    def accept(self, text):
        text = text.strip()
        if not text:
            return None
        match = self.pattern.search(text)
        if match:
            request = text[match.end():].lstrip(' \t\r\n!！.,，。:：;；?？-—')
            if not request:
                self.deadline = self.clock() + self.timeout
                return None
            self.reset()
            return request
        if not self.waiting:
            self.reset()
            return text
        return None


def sync_wake_phrase(box, gate):
    keyword = box.wake_phrase()
    if keyword == gate.keyword:
        return False
    gate.set_keyword(keyword)
    print(f'Wake phrase: {gate.keyword}', flush=True)
    return True


def show_wake_state(box, gate):
    waiting = gate.waiting
    message = (f'Say "{gate.keyword}!" to wake me.\nOr say wake word + request.' if waiting else
               f'Awake! Speak your request.\nWaiting up to {gate.remaining:.0f} seconds.')
    box.expression('sleeping' if waiting else 'listening')
    box.display(message, 'en')
    print(message.replace('\n', ' '), flush=True)
    return waiting


def pcm_level(pcm):
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    return sum(abs(int(sample)) for sample in samples) / max(1, len(samples))


def listen_once(box, recognizer, seconds=4, save_recording=None, automatic=False, threshold=80, silence=0.6,
                announce=True, wake_waiting=False):
    """Recognize one contiguous device recording without an amplitude gate."""
    language = recognizer.language
    capture_started = time.monotonic()
    if automatic:
        if announce:
            show_status(box, 'listening', f'Listening ({language}) \U0001F3A4\nSpeak naturally.\nPause to send your message.', 'en')
            print(f'Listening ({language}): pause {silence:g}s to send...', flush=True)
        pcm = box.capture_speech(threshold, silence)
        if not pcm:
            return ''
    else:
        if announce:
            show_status(box, 'listening', f'Listening ({language}) \U0001F3A4\nSpeak now for {seconds:g} seconds.', 'en')
        print(f'Listening ({language}): speak now for {seconds:g} seconds...', flush=True)
        pcm = box.capture(seconds)
    print(f'LATENCY stage=capture_receive elapsed_ms={(time.monotonic()-capture_started)*1000:.0f} audio_ms={len(pcm)/32:.0f}', flush=True)
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    peak = max((abs(int(value)) for value in samples), default=0)
    mean = pcm_level(pcm)
    print(f'Microphone: mean={mean:.1f}, peak={peak}, duration={len(pcm) / 32000:.2f}s', flush=True)
    if save_recording is not None:
        with wave.open(str(save_recording), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
    if peak == 0:
        print('No microphone signal: recording contains only zeros. Check microphone initialization.', flush=True)
        box.display('No microphone signal\nPCM is all zeros.\nCheck codec initialization.', 'en')
        return ''
    if not wake_waiting:
        show_status(box, 'thinking', 'Recognizing speech... \U0001F914', 'en')
    stt_started = time.monotonic()
    text = recognizer.transcribe(pcm)
    print(f'LATENCY stage=stt elapsed_ms={(time.monotonic()-stt_started)*1000:.0f}', flush=True)
    if not text:
        print(f'No speech recognized. Selected model: {language}. '
              'Check the recording and selected language.', flush=True)
        if not wake_waiting:
            box.display('No speech recognized\nCheck language and mic audio.\nTrying again...', 'en')
    return text


def show_status(box, state, text, language='en'):
    """Update the avatar without erasing the last conversation page."""
    status = getattr(box, 'status', '')
    if isinstance(status, str) and Box3.reply_fields(status).get('face') == '1':
        box.expression(state)
    else:
        box.display(text, language)


class VoiceActivity:
    """Amplitude VAD with pre-roll, trailing silence, and bounded utterances."""
    def __init__(self, threshold=500, silence=1.0, maximum=10.0):
        self.threshold = threshold
        self.silence = silence
        self.maximum = maximum
        self.reset()

    def reset(self):
        self.preroll = deque(maxlen=2)
        self.chunks = []
        self.quiet = 0.0
        self.duration = 0.0

    def feed(self, pcm):
        seconds = len(pcm) / 32000
        loud = pcm_level(pcm) >= self.threshold
        if not self.chunks:
            if not loud:
                self.preroll.append(pcm)
                return None
            self.chunks = list(self.preroll)
            self.duration = sum(map(len, self.chunks)) / 32000
            self.preroll.clear()
        self.chunks.append(pcm)
        self.duration += seconds
        self.quiet = 0 if loud else self.quiet + seconds
        if self.quiet >= self.silence or self.duration >= self.maximum:
            utterance = b''.join(self.chunks)
            self.reset()
            return utterance
        return None


def display_pages(text, limit=1024):
    """Never split a UTF-8 scalar when applying the USB text payload limit."""
    page = ''
    size = 0
    for character in text.replace('\0', ''):
        length = len(character.encode('utf-8'))
        if size + length > limit:
            yield page
            page, size = '', 0
        page += character
        size += length
    if page:
        yield page


def pi_prompt(text):
    return ('Reply concisely for spoken playback, in under 50 words. '
              'Use Traditional Chinese when the user speaks Chinese; otherwise use English. '
              'Lead with a short complete sentence, then add details only if needed. '
              'For general questions, avoid exploring the workspace; use only the tools needed to answer. '
              'Avoid code blocks unless explicitly requested. Do not claim to search for or play music; '
              'music playback is handled by the host using local files. '
              'Use available weather or web tools for current weather; fetch fresh data for this request instead of reusing earlier weather numbers. Never invent live conditions. '
              'Do not access BOX-3 over USB or TCP; the voice host owns the device connection. User request:\n' + text)


def ask_pi(text, session, timeout=180, no_extensions=False, on_delta=None, cancel=None):
    prompt = pi_prompt(text)
    argv = ['pi', '--print', '--thinking', 'off',
            '--exclude-tools', 'box3_*,get_room_temperature,jukebox_control']
    if no_extensions:
        argv.append('--no-extensions')
    argv.extend(['--session', str(session), prompt])
    if on_delta is not None:
        return stream_pi(argv, on_delta, timeout, cancel)
    result = subprocess.run(argv,
                            input='', capture_output=True, text=True, encoding='utf-8',
                            timeout=timeout, check=True)
    if not result.stdout.strip():
        raise RuntimeError('Pi returned an empty reply')
    return result.stdout.strip()


def keyboard_loop(commands):
    while True:
        try:
            text = input('Prompt (/quit, /music PATH, /transport usb|wifi|status): ').strip()
        except (EOFError, KeyboardInterrupt):
            return
        if text:
            commands.put(text)
            if text == '/quit':
                return


def reply_language(text):
    return 'zh-TW' if re.search(r'[\u3400-\u9FFF]', text) else 'en'


def conversation_pages(text, language, width=208, rows=6):
    """Fit the conversation column beside the avatar, with one speaker-label line."""
    def character_width(character):
        if character in ('\uFE0E', '\uFE0F') or unicodedata.combining(character):
            return 0
        if ord(character) >= 0x1F000 or character in '\u231B\u2705\u274C\u26A0\u2764':
            return 18
        if ord(character) < 128:
            return 6 if language == 'en' else 8
        return 16

    lines, line, used = [], '', 0
    # Keep English words intact when possible; CJK characters wrap individually.
    for token in re.findall(r'\n|[A-Za-z0-9\x27]+|[^\n]', text.replace('\0', '')):
        token_width = sum(map(character_width, token))
        if token == '\n' or (line and used + token_width > width):
            lines.append(line)
            line, used = '', 0
            if len(lines) == rows:
                yield '\n'.join(lines)
                lines = []
            if token == '\n':
                continue
        for character in token:
            size = character_width(character)
            if line and used + size > width:
                lines.append(line)
                line, used = '', 0
                if len(lines) == rows:
                    yield '\n'.join(lines)
                    lines = []
            line += character
            used += size
    if line or lines:
        yield '\n'.join(lines + ([line] if line else []))


def show_user_message(box, text, agent_name='Pi'):
    print(f'\nYou: {text}\n{agent_name}: replying...\n', flush=True)
    box.expression('thinking')
    language = reply_language(text)
    pages = list(conversation_pages(text, language))
    for index, page in enumerate(pages):
        box.display(f'You ({index + 1}/{len(pages)})\n{page}', language)
        if index + 1 < len(pages):
            time.sleep(2)


def speak_reply(box, text, temp, agent_name='Pi', expression='speaking'):
    print(f'\n{agent_name}: {text}\n', flush=True)
    box.expression(expression)
    language = reply_language(text)
    pages = list(conversation_pages(text, language))
    output = Path(temp) / 'reply.wav'
    for index, page in enumerate(pages):
        box.display(f'{agent_name} ({index + 1}/{len(pages)})\n{page}', language)
        started = time.monotonic()
        print(f'Synthesizing speech ({index + 1}/{len(pages)})...', flush=True)
        synthesize(page.replace('\n', ' '), output, language)
        print(f'Speech ready in {time.monotonic() - started:.1f}s.', flush=True)
        box.play(output, progress=lambda message: print(message, flush=True))


def music_query(text):
    patterns = (r'^(?:\u6211\u60F3\u807D|\u6211\u8981\u807D|\u6211\u60F3\u8981\u807D|\u8ACB\u64AD\u653E|\u64AD\u653E|\u653E\u4E00\u9996|\u653E\u9996)\s*(.+)$',
                r'^(?:(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?'
                r'(?:play|put\s+on|listen\s+to)|'
                r'(?:i\s+(?:would\s+like|want|like)|i[\'\u2019]d\s+like)'
                r'\s+to\s+(?:listen\s+to|hear))\s+(.+)$')
    for pattern in patterns:
        match = re.match(pattern, text.strip(), re.IGNORECASE)
        if match:
            query = match.group(1).strip()
            query = re.sub(r'^(?:the\s+)?(?:song|track|music)(?:\s+(?:called|named))?\s+',
                           '', query, flags=re.IGNORECASE)
            query = re.sub(r'[,\s]+please[.!?]*$', '', query, flags=re.IGNORECASE)
            query = query.strip(' \u300C\u300D\u300A\u300B\"\'\u3002.!\uFF01?\uFF1F')
            return query or None
    return None


def find_local_music(directory, query):
    def normalize(value):
        return re.sub(r'[\W_]+', '', value).casefold()
    key = normalize(query)
    if not key or not directory.is_dir():
        return []
    supported = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.opus', '.aac'}
    matches = [path for path in directory.rglob('*') if path.is_file() and
               path.suffix.lower() in supported and key in normalize(path.stem)]
    exact = [path for path in matches if normalize(path.stem) == key]
    return sorted(exact or matches)


def play_local_music(box, source, temp, backend='mpv'):
    print(f'Music: {source}', flush=True)
    box.expression('music')
    box.display('Music \U0001F50A\n' + source.stem[:100], reply_language(source.stem))
    output = Path(temp) / 'music.wav'
    print('Preparing music...', flush=True)
    render_music(source, output, backend)
    box.play(output, progress=lambda message: print(message, flush=True))


def connection_options(port=None, host=None, tcp_port=8233, preferred=None):
    explicit = 'wifi' if host else ('wifi' if port.startswith('socket://') else 'usb') if port else None
    port = port or os.environ.get('BOX3_PORT')
    host = host or os.environ.get('BOX3_HOST')
    endpoints = {}
    if port:
        endpoints['wifi' if port.startswith('socket://') else 'usb'] = port
    if host:
        endpoints['wifi'] = f'socket://{host}:{tcp_port}'
    selected = preferred or explicit or ('wifi' if 'wifi' in endpoints else 'usb')
    if endpoints and selected not in endpoints:
        raise ValueError(f'{selected.upper()} endpoint is not configured')
    return endpoints, selected


def main():
    ruview_defaults = saved_configuration()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('pi', 'openai', 'gemini', 'openclaw'), default='pi',
                        help='Reply backend (default: pi)')
    parser.add_argument('--model', help='Model ID (OpenClaw: openclaw/<agentId>); or set BOX3_PROVIDER_MODEL')
    parser.add_argument('--port', help='USB port or socket://HOST:PORT (default: BOX3_PORT)')
    parser.add_argument('--host', help='BOX-3 Wi-Fi IP or hostname (default: BOX3_HOST)')
    parser.add_argument('--transport', choices=('usb', 'wifi'), help='Initial transport when both endpoints are configured')
    parser.add_argument('--tcp-port', type=int, default=8233, help='BOX-3 TCP port (default: 8233)')
    parser.add_argument('--language', choices=('auto', 'en', 'zh'), default='auto',
                        help='Whisper auto supports Chinese/English without switching models')
    parser.add_argument('--stt-backend', choices=('whisper', 'vosk'), default='whisper')
    parser.add_argument('--whisper-model', default=os.environ.get('BOX3_WHISPER_MODEL', 'small'),
                        help='Multilingual faster-whisper model name or local model directory')
    parser.add_argument('--threshold', type=float, default=80)
    parser.add_argument('--silence', type=float, default=0.6)
    parser.add_argument('--stream-capture', action='store_true', help='Experimental Wi-Fi LISTENSTREAM capture (default: stable LISTEN/pull)')
    parser.add_argument('--no-stream-replies', action='store_true', help='Use complete replies and legacy Piper CLI for comparison')
    parser.add_argument('--whisper-beam-size', type=int, choices=range(1, 6), default=1, help='Whisper beam width (1 is faster; 5 uses more CPU)')
    parser.add_argument('--keyboard-only', action='store_true')
    parser.add_argument('--wake-word', help='Override the device wake phrase (default: Settings value, or Osiris on older firmware)')
    parser.add_argument('--no-wake-word', action='store_true', help='Send spoken requests without waking first')
    parser.add_argument('--wake-timeout', type=float, default=15,
                        help='Seconds to accept a request after a standalone wake phrase (default: 15)')
    parser.add_argument('--followup-timeout', type=float, default=30,
                        help='Stay awake after each completed reply (seconds, default: 30)')
    ruview_switch = parser.add_mutually_exclusive_group()
    ruview_switch.add_argument('--ruview', dest='ruview_enabled', action='store_true', default=None)
    ruview_switch.add_argument('--no-ruview', dest='ruview_enabled', action='store_false')
    parser.add_argument('--ruview-mqtt-host', help='Enable RuView presence wake via this MQTT broker')
    parser.add_argument('--ruview-mqtt-port', type=int, default=1883)
    parser.add_argument('--ruview-presence-topic', help='Exact presence state_topic from RuView MQTT discovery')
    parser.add_argument('--ruview-mqtt-username')
    parser.add_argument('--ruview-mqtt-password-env', default='MQTT_PASSWORD')
    parser.add_argument('--ruview-mqtt-tls', action='store_true')
    parser.add_argument('--ruview-on-payload', default='ON')
    parser.add_argument('--ruview-off-payload', default='OFF')
    parser.add_argument('--pi-one-shot', action='store_true', help='Use one Pi CLI process per request instead of persistent RPC')
    parser.add_argument('--no-tts-warmup', action='store_true', help='Load Piper voices on first reply instead of startup')
    parser.add_argument('--pi-no-extensions', action='store_true',
                        help='Disable Pi extension discovery for troubleshooting')
    parser.add_argument('--music-dir', type=Path, default=Path('~/Music').expanduser(),
                        help='Local music library searched by spoken song title')
    parser.add_argument('--music-backend', choices=('mpv', 'ffmpeg'), default='mpv')
    parser.add_argument('--capture-mode', choices=('auto', 'window', 'vad'), default='auto',
                        help='auto ends on a pause on the device; window is fixed length; vad is experimental')
    parser.add_argument('--record-seconds', type=float, default=4,
                        help='Continuous recording length in window mode (0.1 to 10 seconds)')
    parser.add_argument('--save-recording', type=Path,
                        help='Overwrite this WAV with the latest window for microphone diagnosis')
    args = parser.parse_args()
    enabled = args.ruview_enabled
    if enabled is None:
        enabled = bool(args.ruview_mqtt_host or args.ruview_presence_topic) or ruview_defaults.get('enabled', False)
    if enabled:
        args.ruview_mqtt_host = args.ruview_mqtt_host or ruview_defaults.get('ruview_mqtt_host')
        args.ruview_presence_topic = args.ruview_presence_topic or ruview_defaults.get('ruview_presence_topic')
        if not args.ruview_mqtt_host or not args.ruview_presence_topic:
            parser.error('RuView is enabled: configure MQTT host and presence topic in configure.py or CLI')
    else:
        args.ruview_mqtt_host = args.ruview_presence_topic = None
    if bool(args.ruview_mqtt_host) != bool(args.ruview_presence_topic):
        parser.error('RuView requires both --ruview-mqtt-host and --ruview-presence-topic')
    if args.ruview_mqtt_host:
        if args.keyboard_only or args.no_wake_word:
            parser.error('RuView presence wake requires voice mode with wake gating enabled')
        if not 1 <= args.ruview_mqtt_port <= 65535:
            parser.error('MQTT port must be 1..65535')
        if any(c in args.ruview_presence_topic for c in '+#'):
            parser.error('Use one exact RuView presence topic without wildcards')
        if not args.ruview_on_payload or not args.ruview_off_payload or args.ruview_on_payload == args.ruview_off_payload:
            parser.error('Presence ON/OFF payloads must be nonempty and distinct')
    if not 1 <= args.tcp_port <= 65535:
        parser.error('TCP port must be 1..65535')
    try:
        endpoints, preferred = connection_options(args.port, args.host, args.tcp_port, args.transport)
    except ValueError as exc:
        parser.error(str(exc))
    if not endpoints:
        parser.error('Pass --host BOX_IP or --port USB_PORT, or set BOX3_HOST / BOX3_PORT')
    if not 0 < args.threshold <= 32768 or not 0.25 <= args.silence <= 5:
        parser.error('Threshold must be 1..32768 and silence 0.25..5 seconds')
    if not 0.1 <= args.record_seconds <= 10:
        parser.error('Recording length must be 0.1..10 seconds')
    if not 1 <= args.wake_timeout <= 120:
        parser.error('Wake timeout must be 1..120 seconds')
    if not 1 <= args.followup_timeout <= 120:
        parser.error('Follow-up timeout must be 1..120 seconds')
    try:
        wake_gate = None if args.no_wake_word or args.keyboard_only else WakeWordGate(
            args.wake_word if args.wake_word is not None else 'Osiris', args.wake_timeout, followup_timeout=args.followup_timeout)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        cloud = None if args.provider == 'pi' else CloudChat(args.provider, args.model)
    except ValueError as exc:
        parser.error(str(exc))
    agent_name = {'pi': 'Pi', 'openai': 'OpenAI', 'gemini': 'Gemini', 'openclaw': 'OpenClaw'}[args.provider]
    wake_ui = None
    recognizer = None if args.keyboard_only else create_recognizer(
        args.language, args.stt_backend, args.whisper_model)
    if recognizer is not None and args.stt_backend == 'whisper':
        recognizer.beam_size = args.whisper_beam_size
    commands = queue.Queue(maxsize=16)
    threading.Thread(target=keyboard_loop, args=(commands,), daemon=True).start()
    vad = VoiceActivity(args.threshold, args.silence)
    box = Box3Connection(endpoints, preferred, stream_capture=args.stream_capture)
    listening_announced = False
    wake_next_poll = 0
    try:
        with tempfile.TemporaryDirectory(prefix='box3-agent-') as temp, ExitStack() as resources:
            presence = None
            if args.ruview_mqtt_host:
                presence = RuViewPresence(
                    args.ruview_mqtt_host, args.ruview_mqtt_port, args.ruview_presence_topic,
                    args.ruview_mqtt_username, os.environ.get(args.ruview_mqtt_password_env),
                    args.ruview_on_payload, args.ruview_off_payload, args.ruview_mqtt_tls)
                resources.callback(presence.close)
                print('RuView presence wake enabled; waiting for live MQTT presence.', flush=True)
            session = Path(temp) / 'pi-session.jsonl'
            if not args.no_stream_replies and not args.no_tts_warmup and not args.keyboard_only:
                print('Preparing Piper voices before listening...', flush=True)
                warmup_resident(('zh-TW', 'en'))
            persistent_pi = None
            if cloud is None and not args.no_stream_replies and not args.pi_one_shot:
                argv = ['pi', '--mode', 'rpc', '--thinking', 'off', '--exclude-tools',
                        'box3_*,get_room_temperature,jukebox_control', '--session', str(session)]
                if args.pi_no_extensions:
                    argv.append('--no-extensions')
                persistent_pi = PiRPC(argv, prompt_builder=pi_prompt)
                resources.callback(persistent_pi.close)
                print('Starting persistent Pi RPC...', flush=True)
                persistent_pi.start()
            box.display(agent_name + ' voice agent ready \U0001F916 \U0001F3A4', 'en')
            print(f'Reply provider: {agent_name}' + (f' | Model: {cloud.model}' if cloud else ''), flush=True)
            print('Firmware:', box.status, flush=True)
            print('BOX-3 voice agent ready. Listening is paused during Pi requests and playback.')
            while True:
                try:
                    try:
                        box.poll_transport()
                    except (RuntimeError, ValueError) as exc:
                        print('Transport switch:', exc, file=sys.stderr)
                    if wake_gate is not None and args.wake_word is None and time.monotonic() >= wake_next_poll:
                        wake_next_poll = time.monotonic() + 2
                        try:
                            if sync_wake_phrase(box, wake_gate):
                                wake_ui = None
                        except (RuntimeError, ValueError) as exc:
                            print('Wake setting:', exc, file=sys.stderr)
                    if presence is not None and presence.consume() and wake_gate.waiting:
                        wake_gate.arm_presence()
                        wake_ui = None
                        print('RuView arrival: accepting a spoken request.', flush=True)
                    if wake_gate is not None and wake_ui != wake_gate.waiting:
                        wake_ui = show_wake_state(box, wake_gate)
                    try:
                        text = commands.get(timeout=0.1) if args.keyboard_only else commands.get_nowait()
                        vad.reset()
                    except queue.Empty:
                        if args.keyboard_only:
                            continue
                        if args.capture_mode == 'auto':
                            text = listen_once(box, recognizer, save_recording=args.save_recording,
                                               automatic=True, threshold=args.threshold, silence=args.silence,
                                               announce=wake_gate is None and not listening_announced,
                                               wake_waiting=wake_gate is not None and wake_gate.waiting)
                            listening_announced = True
                        elif args.capture_mode == 'window':
                            text = listen_once(box, recognizer, args.record_seconds, args.save_recording,
                                               announce=wake_gate is None,
                                               wake_waiting=wake_gate is not None and wake_gate.waiting)
                        else:
                            # Experimental VAD batches have transfer gaps. Prefer
                            # window mode when recognition is unreliable.
                            pcm = box.capture(0.25)
                            print(f'VAD microphone level: {pcm_level(pcm):.1f}; threshold={args.threshold:g}', flush=True)
                            utterance = vad.feed(pcm)
                            if utterance is None:
                                continue
                            text = recognizer.transcribe(utterance)
                            if not text:
                                print('No speech recognized from VAD utterance. Try --capture-mode window.', flush=True)
                        if not text:
                            continue
                        listening_announced = False
                        if wake_gate is not None:
                            if presence is not None and presence.consume() and wake_gate.waiting:
                                wake_gate.arm_presence()
                                wake_ui = None
                            text = wake_gate.accept(text)
                            if text is None:
                                continue
                    if text == '/quit':
                        break
                    if text.startswith('/transport'):
                        target = text.split(maxsplit=1)[1].strip().lower() if ' ' in text else 'status'
                        try:
                            if target != 'status':
                                box.switch(target)
                            print(f'Transport: {box.active.upper()} | Configured: {", ".join(box.endpoints)}', flush=True)
                        except (ValueError, RuntimeError) as exc:
                            print('Transport switch:', exc, file=sys.stderr)
                        continue
                    response_completed = False
                    try:
                        if text.startswith('/music '):
                            source = Path(text[7:].strip()).expanduser()
                            play_local_music(box, source, temp, args.music_backend)
                        else:
                            show_user_message(box, text, agent_name)
                            query = music_query(text)
                            if query is not None:
                                matches = find_local_music(args.music_dir.expanduser(), query)
                                if len(matches) == 1:
                                    play_local_music(box, matches[0], temp, args.music_backend)
                                elif matches:
                                    names = ', '.join(path.stem for path in matches[:5])
                                    speak_reply(box, '\u627E\u5230\u591A\u500B\u7248\u672C\uFF0C\u8ACB\u8AAA\u51FA\u66F4\u5B8C\u6574\u7684\u6A94\u540D\uFF1A' + names, temp)
                                else:
                                    speak_reply(box, '\u672C\u6A5F\u97F3\u6A02\u8CC7\u6599\u593E\u627E\u4E0D\u5230\u9019\u9996\u6B4C\u3002\u8ACB\u5148\u653E\u5165\u97F3\u6A02\u6A94\uFF0C\u518D\u8AAA\u6B4C\u540D\u3002', temp)
                            else:
                                streaming = not args.no_stream_replies and (cloud is None or cloud.streaming is True)
                                fields = Box3.reply_fields(box.status)
                                llm_emotion = fields.get('emotion') == 'llm' and fields.get('moods') == '1'
                                if cloud is not None:
                                    cloud.emotion_mode = llm_emotion
                                if streaming:
                                    if persistent_pi is not None:
                                        backend = persistent_pi
                                    elif cloud is None:
                                        class PiBackend:
                                            def __init__(self):
                                                self.cancel_event = threading.Event()
                                            def cancel(self):
                                                self.cancel_event.set()
                                            def ask(self, prompt, on_delta):
                                                return ask_pi(prompt, session, no_extensions=args.pi_no_extensions, on_delta=on_delta, cancel=self.cancel_event)
                                        backend = PiBackend()
                                    else:
                                        backend = cloud
                                    if llm_emotion:
                                        backend = EmotionBackend(backend)
                                    stream_reply(box, backend, text, temp, agent_name, reply_language, conversation_pages)
                                else:
                                    llm_started = time.monotonic()
                                    class OneShotPi:
                                        def ask(self, prompt):
                                            return ask_pi(prompt, session, no_extensions=args.pi_no_extensions)
                                    backend = cloud if cloud is not None else OneShotPi()
                                    if llm_emotion:
                                        backend = EmotionBackend(backend)
                                    reply = backend.ask(text)
                                    print(f'LATENCY stage=llm elapsed_ms={(time.monotonic()-llm_started)*1000:.0f}', flush=True)
                                    speak_reply(box, reply, temp, agent_name,
                                                expression=getattr(backend, 'emotion_expression', 'speaking'))
                        response_completed = True
                    except (Exception, KeyboardInterrupt) as exc:
                        if isinstance(exc, KeyboardInterrupt):
                            raise
                        print('Voice agent error:', exc, file=sys.stderr)
                        box.expression('error')
                        box.display('Request failed \u274C\nSee host terminal.', 'en')
                    finally:
                        vad.reset()
                        listening_announced = False
                        # Discard the first post-playback batch to reduce stale DMA
                        # audio triggering the next utterance. No echo cancellation.
                        if recognizer is not None and getattr(box, 'synchronized', True):
                            box.capture(0.1)
                        if wake_gate is not None:
                            if response_completed:
                                wake_gate.arm_followup()
                            else:
                                wake_gate.reset()
                            wake_ui = None
                except (OSError, RuntimeError, ValueError) as exc:
                    # Capture/STT/wake-screen errors previously escaped the loop
                    # and closed TCP, causing the device to appear to switch to USB.
                    print(f'Voice input/connection error: {exc}', file=sys.stderr, flush=True)
                    vad.reset()
                    listening_announced = False
                    wake_ui = None
                    if wake_gate is not None:
                        wake_gate.reset()
                    try:
                        box.reconnect()
                        print('Device reconnected; failed utterance was discarded. Please speak again.', flush=True)
                    except (OSError, RuntimeError, ValueError) as recovery_error:
                        print(f'Device reconnect failed: {recovery_error}', file=sys.stderr, flush=True)
                        time.sleep(1)
    finally:
        if cloud is not None:
            cloud.close()
        box.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nVoice agent stopped.')
    except Exception as exc:
        print(f'Voice agent: {exc}', file=sys.stderr)
        sys.exit(1)
