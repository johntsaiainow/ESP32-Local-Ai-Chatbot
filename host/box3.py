"""USB/TCP client for BOX-3 protocol v1; all speech processing runs on the host."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave
import zlib
import math
import struct
import secrets
import select
import socket

RATE = 16000
MAX_BYTES = 320000
LANGUAGES = ('en', 'zh', 'zh-TW', 'ja', 'ko')


class IncompleteRecording(RuntimeError):
    def __init__(self, audio, expected, status):
        self.audio = audio
        super().__init__(f'Recording incomplete: captured {len(audio)}/{expected} bytes '
                         f'({len(audio) / 32000:.2f}/{expected / 32000:.2f} seconds). {status}')


class Box3:
    def __init__(self, port, timeout=30, serial_factory=None):
        if serial_factory is None:
            import serial
            if port.startswith('socket://'):
                from serial.urlhandler.protocol_socket import Serial as SocketSerial

                class BufferedSocketSerial(SocketSerial):
                    def open(self):
                        super().open()
                        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                    def read_available(self):
                        # pyserial socket.in_waiting reports readiness (0/1),
                        # not queued bytes. recv drains a batch without waiting
                        # for a 4096-byte serial read to fill or time out.
                        ready, _, _ = select.select([self._socket], [], [], self.timeout)
                        if not ready:
                            return b''
                        try:
                            data = self._socket.recv(4096)
                        except BlockingIOError:
                            return b''
                        if not data:
                            raise serial.SerialException('BOX-3 TCP connection closed')
                        return data

                def serial_factory(**kwargs):
                    kwargs.pop('port', None)
                    kwargs.pop('exclusive', None)
                    return BufferedSocketSerial(port=None, **kwargs)
            else:
                serial_factory = serial.Serial
        self.serial = serial_factory(port=None, baudrate=115200, timeout=0.2,
                                     write_timeout=5, exclusive=True)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.timeout = timeout
        self.pending = bytearray()
        self.synchronized = True
        # File locking via exclusive=True prevents competing clients on POSIX.
        try:
            self.serial.reset_input_buffer()
            _, self.status = self.command('PING')
            self.command('CANCEL')
        except Exception:
            self.close()
            raise

    def close(self):
        self.serial.close()

    def recover(self):
        """Drain stale acknowledgements through a unique device reset barrier."""
        token = secrets.token_hex(8)
        self.command('RESET ' + token, _sync_token=token)

    def synchronize_playback(self):
        """Find a unique reply boundary without cancelling buffered audio."""
        token = secrets.token_hex(8)
        # Terminate any incomplete command left by a dropped USB packet.
        if self.serial.write(b'\n') != 1:
            raise RuntimeError('Unable to terminate partial USB command')
        _, ack = self.command('SYNC ' + token, _sync_token=token, _timeout=5)
        return self.reply_fields(ack)

    def command(self, command, max_data=0, _sync_token=None, _timeout=None):
        if not getattr(self, 'synchronized', True) and _sync_token is None:
            raise RuntimeError('USB protocol is out of sync; reset/reconnect BOX-3 before continuing')
        packet = ('BOX1 ' + command + '\n').encode('ascii')
        fields = self.reply_fields(getattr(self, 'status', ''))
        large_rx = fields.get('rx') == '4096'
        # Old firmware has a 256-byte RX queue with no backpressure. Pace long
        # text commands rather than dumping their whole line into that queue.
        chunk_size = len(packet) if large_rx or len(packet) <= 192 else 64
        for offset in range(0, len(packet), chunk_size):
            part = packet[offset:offset + chunk_size]
            sent = 0
            while sent < len(part):
                count = self.serial.write(part[sent:])
                if not count:
                    raise RuntimeError('Serial command write made no progress')
                sent += count
            if offset + chunk_size < len(packet):
                self.serial.flush()
                time.sleep(0.002)
        self.serial.flush()
        deadline = time.monotonic() + (self.timeout if _timeout is None else _timeout)
        data = bytearray()
        protocol_error = None
        while time.monotonic() < deadline:
            # Wait for one byte, then consume available data without adding a
            # full serial timeout to every stop-and-wait audio packet.
            reader = getattr(self.serial, 'read_available', None)
            chunk = reader() if reader is not None else self.serial.read(
                max(1, min(4096, self.serial.in_waiting)))
            self.pending.extend(chunk)
            if len(self.pending) > 65536:
                raise RuntimeError('Serial input exceeded the protocol buffer limit')
            while b'\n' in self.pending:
                line, _, rest = self.pending.partition(b'\n')
                self.pending = bytearray(rest)
                if line.startswith(b'BOX1 ERR '):
                    if _sync_token is not None:
                        continue
                    raise RuntimeError(line.decode('ascii', errors='replace'))
                if line.startswith(b'BOX1 DATA '):
                    if _sync_token is not None:
                        continue
                    try:
                        payload = bytes.fromhex(line[10:].decode('ascii'))
                    except ValueError:
                        # Consume the terminal reply before raising, so a future
                        # command cannot mistake this recording's OK for its own.
                        protocol_error = RuntimeError(
                            f'Malformed audio response ({len(line)} bytes; '
                            f'prefix={bytes(line[:80])!r}). '
                            'Upload the latest firmware and close other serial clients.')
                        continue
                    if len(data) + len(payload) > max_data:
                        protocol_error = RuntimeError('Unexpected or oversized audio response')
                    elif protocol_error is None:
                        data.extend(payload)
                elif line.startswith(b'BOX1 OK'):
                    if _sync_token is not None:
                        if self.reply_fields(line.decode('ascii')).get('sync') != _sync_token:
                            continue
                        self.synchronized = True
                    if protocol_error is not None:
                        raise protocol_error
                    return bytes(data), line.decode('ascii')
                # Ignore boot diagnostics and volume log lines.
        if protocol_error is not None:
            raise protocol_error
        self.synchronized = False
        raise TimeoutError(f'BOX-3 did not respond to {command.split()[0]} '
                           f'({len(packet)} command bytes); check firmware, port, and USB connection')

    def expression(self, state):
        extra_states = {'sleeping': 'happy', 'waiting': 'thinking', 'surprised': 'happy',
                        'love': 'happy', 'success': 'happy', 'warning': 'error'}
        if state not in ('happy', 'sad', 'listening', 'thinking', 'speaking', 'music', 'error') and state not in extra_states:
            raise ValueError('Unsupported agent expression')
        fields = self.reply_fields(self.status)
        if fields.get('face') == '1':
            if fields.get('emojistates') != '1':
                state = extra_states.get(state, state)
            self.command('FACE ' + state)

    def display(self, text, language='en'):
        encoded = text.encode('utf-8')
        if language not in LANGUAGES or len(encoded) > 1024 or b'\0' in encoded:
            raise ValueError('Text must be at most 1024 UTF-8 bytes without NUL; select a supported language')
        self.command('TEXT ' + language + ' ' + encoded.hex())

    def capture(self, seconds=5):
        if not 0.1 <= seconds <= 10:
            raise ValueError('Recording duration must be between 0.1 and 10 seconds')
        expected = int(seconds * RATE) * 2
        if 'audio=pull1' not in self.status.split():
            raise RuntimeError('Recording requires audio=pull1 firmware. '
                               'Upload the current firmware to the connected BOX-3 first.')
        _, status = self.command(f'RECORD {expected}')
        metadata = self.reply_fields(status)
        try:
            captured = int(metadata.get('bytes', '0'))
        except ValueError:
            captured = 0
        partial = metadata.get('partial') == '1' and metadata.get('expected') == str(expected)
        if (metadata.get('audio') != 'pull1' or not 0 < captured <= expected or captured % 2 or
                (captured != expected and not partial)):
            raise RuntimeError(f'Recording acknowledgement mismatch: expected {expected} bytes, got {status}')
        recording_status = status
        return self._pull_recording(captured, expected, recording_status)

    def capture_speech(self, threshold=80, silence=1.0):
        if self.reply_fields(self.status).get('vad') != '1':
            raise RuntimeError('Automatic endpointing requires vad=1 firmware. Upload the current firmware first.')
        if not 1 <= threshold <= 32768 or not 0.25 <= silence <= 5:
            raise ValueError('Invalid speech threshold or silence duration')
        _, status = self.command(f'LISTEN {int(threshold)} {int(silence * 1000)} 2000')
        fields = self.reply_fields(status)
        try:
            captured = int(fields.get('bytes', '-1'))
        except ValueError:
            captured = -1
        if fields.get('audio') != 'pull1' or not 0 <= captured <= MAX_BYTES or captured % 2:
            raise RuntimeError(f'Invalid LISTEN acknowledgement: {status}')
        if captured == 0:
            return b''
        if fields.get('reason') == 'limit':
            print('Speech reached the ten-second recording limit.', file=sys.stderr, flush=True)
        return self._pull_recording(captured, captured, status)

    def _pull_recording(self, captured, expected, recording_status):
        data = bytearray()
        cleanup = True
        try:
            while len(data) < captured:
                offset = len(data)
                read_size = self.network_block_size('netread', 256)
                count = min(read_size, captured - offset)
                for attempt in range(3):
                    try:
                        request = f'READ {offset}' + (f' {count}' if read_size > 256 else '')
                        block, status = self.command(request, max_data=count)
                        fields = self.reply_fields(status)
                        checksum = f'{zlib.crc32(block):08x}'
                        if (len(block) != count or fields.get('offset') != str(offset) or
                                fields.get('bytes') != str(count) or fields.get('crc') != checksum):
                            raise RuntimeError(f'Audio block {offset}: received {len(block)}/{count} bytes; '
                                               f'checksum/offset acknowledgement: {status}')
                        data.extend(block)
                        break
                    except TimeoutError:
                        # A missing terminal reply leaves the stream ambiguous;
                        # reconnect rather than issuing a competing request.
                        cleanup = False
                        raise
                    except RuntimeError:
                        if attempt == 2:
                            raise
            if captured != expected:
                raise IncompleteRecording(bytes(data), expected, recording_status)
            return bytes(data)
        finally:
            if cleanup:
                try:
                    self.command('CANCEL')
                except (RuntimeError, TimeoutError, OSError):
                    pass  # The device also expires unused recordings.

    def network_block_size(self, capability, default):
        # Negotiate with firmware; legacy firmware and USB retain old limits.
        if not self.serial.port.startswith('socket://'):
            return default
        try:
            size = int(self.reply_fields(self.status).get(capability, default))
        except ValueError:
            return default
        limit = 8192 if capability == 'netchunk' else 4096
        return size if default <= size <= limit and size % 2 == 0 else default

    @staticmethod
    def reply_fields(status):
        return dict(token.split('=', 1) for token in status.split()[2:] if '=' in token)

    def record(self, output, seconds=5):
        incomplete = None
        try:
            data = self.capture(seconds)
        except IncompleteRecording as exc:
            data, incomplete = exc.audio, exc
        with wave.open(str(output), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(data)
        if incomplete is not None:
            raise RuntimeError(f'{incomplete} Partial WAV saved to {output}; '
                               'this is a diagnostic recording, not a complete capture.') from incomplete

    def play(self, path, progress=None):
        if self.reply_fields(self.status).get('speaker') == '0':
            raise RuntimeError('BOX-3 speaker codec initialization failed; check firmware startup logs')
        with wave.open(str(path), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, RATE, 'NONE'):
                raise ValueError('Playback requires uncompressed mono PCM16 WAV at 16000 Hz')
            streaming = self.reply_fields(self.status).get('stream') == 'ring1'
            while True:
                pcm = wav.readframes(wav.getnframes() if streaming else MAX_BYTES // 2)
                if not pcm:
                    break
                try:
                    _, start_ack = self.command(f"{'STREAM' if streaming else 'PLAY'} {len(pcm)}")
                    start_fields = self.reply_fields(start_ack)
                    if streaming and ('bytes' in start_fields and start_fields['bytes'] != str(len(pcm))):
                        raise RuntimeError(f'Stream size mismatch: sent={len(pcm)} reply={start_ack}')
                    if progress:
                        progress('Streaming to BOX-3 speaker...' if streaming else 'Uploading audio: 0%')
                    reported = 0
                    # Keep legacy DATA lines at 139 bytes, safely below 256.
                    checked = self.reply_fields(self.status).get('upload') == 'checked1'
                    resilient = streaming and self.reply_fields(self.status).get('sync') == '1'
                    block_size = (128 if resilient else 256) if checked else 64
                    if checked:
                        block_size = self.network_block_size('netchunk', block_size)
                    for offset in range(0, len(pcm), block_size):
                        block = pcm[offset:offset + block_size]
                        if checked:
                            packet = f'CHUNK {offset} {zlib.crc32(block):08x} {block.hex()}'
                            attempt = 0
                            busy_deadline = time.monotonic() + 5
                            while True:
                                try:
                                    _, ack = (self.command(packet, _timeout=2) if resilient else self.command(packet))
                                    if self.reply_fields(ack).get('next') != str(offset + len(block)):
                                        raise RuntimeError(f'Playback offset mismatch at {offset}: {ack}')
                                    break
                                except TimeoutError as exc:
                                    attempt += 1
                                    if not resilient or attempt >= 3:
                                        raise TimeoutError(f'{exc}; audio offset={offset}/{len(pcm)} bytes, '
                                                           f'time={offset / (RATE * 2):.2f}s') from exc
                                    state = self.synchronize_playback()
                                    if state.get('failed') == '1':
                                        raise RuntimeError(f'Stream worker failed at {offset}: {state}') from exc
                                    # A lost ACK may follow a committed block; CHUNK replay is idempotent.
                                    if state.get('next') not in (str(offset), str(offset + len(block))):
                                        raise RuntimeError(f'Stream state mismatch at {offset}: {state}') from exc
                                    if progress:
                                        progress(f'USB reply recovered at {offset / (RATE * 2):.2f}s; retrying block')
                                    continue
                                except RuntimeError as exc:
                                    if 'stream_busy' in str(exc):
                                        if time.monotonic() >= busy_deadline:
                                            raise RuntimeError(f'Stream stalled at audio offset={offset}: {exc}') from exc
                                        time.sleep(0.01)
                                        continue
                                    attempt += 1
                                    recoverable = ('chunk_crc' in str(exc) or 'chunk_hex' in str(exc) or
                                                   'Playback offset mismatch' in str(exc))
                                    if not recoverable or attempt >= 3:
                                        raise RuntimeError(
                                            f'{exc}; audio offset={offset}/{len(pcm)} bytes, '
                                            f'time={offset / (RATE * 2):.2f}s, streaming={streaming}') from exc
                        else:
                            self.command('DATA ' + block.hex())
                        percent = min(100, (offset + block_size) * 100 // len(pcm))
                        if progress and percent // 25 > reported // 25:
                            progress(f'Uploading audio: {percent}%')
                            reported = percent
                    if progress:
                        progress('Playing on BOX-3 speaker...')
                    _, end_ack = self.command('END')
                    end_fields = self.reply_fields(end_ack)
                    if progress and 'underruns' in end_fields:
                        progress(f"Audio supply: underruns={end_fields['underruns']}, "
                                 f"stalled_ms={end_fields.get('stalled_ms', '?')}")
                    if progress:
                        progress('Playback complete')
                except Exception:
                    # Cancel explicitly; stream buffers are owned by the playback worker.
                    try:
                        if not getattr(self, 'synchronized', True):
                            self.recover()
                        else:
                            self.command('CANCEL')
                    except Exception:
                        pass
                    raise


class Box3Connection:
    """Keep one controller open and switch it at completed command boundaries."""
    def __init__(self, endpoints, preferred, factory=Box3):
        self.endpoints = dict(endpoints)
        self.factory = factory
        self.active = preferred
        self.device = None
        self._open(preferred)

    def __getattr__(self, name):
        return getattr(self.device, name)

    def _open(self, transport):
        device = self.factory(self.endpoints[transport])
        try:
            supports_link = Box3.reply_fields(device.status).get('link') == '1'
            if len(self.endpoints) > 1 and not supports_link:
                raise RuntimeError('Transport switching requires link=1 firmware; flash the updated firmware')
            if supports_link:
                device.command('LINK SET ' + transport.upper())
                device.command(f'LINK OPTIONS {int("usb" in self.endpoints)} {int("wifi" in self.endpoints)}')
        except Exception:
            device.close()
            raise
        self.device = device
        self.active = transport
        print(f'Transport: {transport.upper()} ({self.endpoints[transport]})', flush=True)

    def switch(self, transport):
        transport = transport.lower()
        if transport not in self.endpoints:
            raise ValueError(f'{transport.upper()} is not configured; provide --port and --host to enable switching')
        if transport == self.active:
            return
        previous = self.active
        self.device.close()
        # Let firmware release TCP ownership / expire its USB handover guard.
        time.sleep(1.1)
        try:
            self._open(transport)
        except Exception as exc:
            time.sleep(1.1)
            self._open(previous)
            raise RuntimeError(f'Cannot switch to {transport.upper()}; restored {previous.upper()}: {exc}') from exc

    def poll_transport(self):
        if Box3.reply_fields(self.device.status).get('link') != '1':
            return
        _, reply = self.device.command('LINK')
        requested = Box3.reply_fields(reply).get('requested')
        if requested in self.endpoints and requested != self.active:
            self.switch(requested)

    def close(self):
        if self.device is not None:
            self.device.close()


def speech_command(variable, values):
    """Use an explicit JSON argv array; text never goes through a shell."""
    configured = os.environ.get(variable)
    if not configured:
        raise RuntimeError(f'Set {variable} to a JSON command array; see host/README.md')
    args = json.loads(configured)
    if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
        raise ValueError(f'{variable} must be a nonempty JSON array of strings')
    # Replace only documented placeholders; preserve braces in other arguments.
    for key, value in values.items():
        args = [arg.replace('{' + key + '}', str(value)) for arg in args]
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          encoding='utf-8', timeout=180).stdout.strip()


def listen(box, language, seconds):
    with tempfile.TemporaryDirectory(prefix='box3-') as temp:
        audio = Path(temp) / 'input.wav'
        box.record(audio, seconds)
        if os.environ.get('BOX3_STT_COMMAND'):
            transcript = speech_command('BOX3_STT_COMMAND', {'input': audio, 'language': language})
        else:
            from offline_speech import transcribe_file
            transcript = transcribe_file(audio, language)
        if not transcript:
            raise RuntimeError('Speech recognition returned an empty transcript')
        return transcript


def say(box, text, language):
    with tempfile.TemporaryDirectory(prefix='box3-') as temp:
        text_file = Path(temp) / 'text.txt'
        output = Path(temp) / 'speech.wav'
        text_file.write_text(text, encoding='utf-8')
        if os.environ.get('BOX3_TTS_COMMAND'):
            speech_command('BOX3_TTS_COMMAND', {'text_file': text_file, 'output': output,
                                               'language': language})
        else:
            from offline_speech import synthesize
            synthesize(text, output, language)
        box.play(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default=os.environ.get('BOX3_PORT'))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('speaker-test', help='Play a one-second test tone without Piper or Pi')
    for action in ('display', 'say'):
        command = sub.add_parser(action)
        command.add_argument('text')
        command.add_argument('--language', choices=LANGUAGES, default='en')
    command = sub.add_parser('play')
    command.add_argument('file', type=Path)
    command = sub.add_parser('record')
    command.add_argument('file', type=Path)
    command.add_argument('--seconds', type=float, default=5)
    command = sub.add_parser('listen')
    command.add_argument('--seconds', type=float, default=5)
    command.add_argument('--language', choices=('auto', 'en', 'zh'), default='auto')
    args = parser.parse_args()
    if not args.port:
        parser.error('Pass --port or set BOX3_PORT, e.g. /dev/ttyACM0')
    box = Box3(args.port)
    try:
        if args.action == 'status':
            print(box.command('PING')[1])
        elif args.action == 'speaker-test':
            with tempfile.TemporaryDirectory(prefix='box3-tone-') as temp:
                path = Path(temp) / 'tone.wav'
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    wav.writeframes(b''.join(struct.pack('<h', int(5000 * math.sin(2 * math.pi * 440 * n / RATE)))
                                             for n in range(RATE)))
                box.play(path, progress=lambda message: print(message, flush=True))
        elif args.action == 'display':
            box.display(args.text, args.language)
        elif args.action == 'record':
            box.record(args.file, args.seconds)
        elif args.action == 'play':
            box.play(args.file, progress=lambda message: print(message, flush=True))
        elif args.action == 'say':
            say(box, args.text, args.language)
        elif args.action == 'listen':
            print(listen(box, args.language, args.seconds))
    finally:
        box.close()


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'BOX-3: {exc}', file=sys.stderr)
        sys.exit(1)
