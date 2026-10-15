import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import wave
import zlib
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('box3', Path(__file__).parents[1] / 'host/box3.py')
box3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(box3)


class FakeSerial:
    def __init__(self, **kwargs):
        self.response = bytearray()
        self.commands = []
        self.recording = struct.pack('<hhh', -32768, 0, 32767)
        self.played = bytearray()
        self.bad_size = False
        self.inject = None
        self.read_fault = None
        self.partial_capture = False
        self.input = bytearray()
        self.write_sizes = []
        self.rx_capacity = 4096
        self.upload = bytearray()
        self.chunk_fault = None

    def open(self):
        pass

    def close(self):
        pass

    def reset_input_buffer(self):
        self.response.clear()

    @property
    def in_waiting(self):
        return len(self.response)

    def flush(self):
        pass

    def write(self, data):
        self.write_sizes.append(len(data))
        # Model HWCDC dropping the tail of a write that exceeds queue space.
        self.input.extend(data[:self.rx_capacity])
        while b'\n' in self.input:
            line, _, rest = self.input.partition(b'\n')
            self.input = bytearray(rest)
            self._handle_packet(line + b'\n')
        return len(data)

    def _handle_packet(self, data):
        command = data.decode('ascii').strip()
        self.commands.append(command)
        if self.inject is not None:
            self.response.extend(self.inject)
            self.inject = None
            return len(data)
        if command.startswith('BOX1 CHUNK '):
            _, _, offset, checksum, payload = command.split()
            offset, payload = int(offset), bytes.fromhex(payload)
            if self.chunk_fault == 'reject_once':
                self.chunk_fault = None
                self.response.extend(b'BOX1 ERR chunk_crc\n')
                return len(data)
            assert zlib.crc32(payload) == int(checksum, 16)
            if offset == len(self.upload):
                self.upload.extend(payload)
                self.played.extend(payload)
            else:
                assert self.upload[offset:offset + len(payload)] == payload
            next_offset = offset + len(payload)
            if self.chunk_fault == 'wrong_ack':
                self.chunk_fault = None
                next_offset += 2
            reply = f'BOX1 OK next={next_offset}\n'.encode()
        elif command.startswith('BOX1 SYNC '):
            reply = (f'BOX1 OK sync={command.split()[-1]} next={len(self.upload)} '
                     f'read={len(self.upload)} failed=0 done=0\n').encode()
        elif command.startswith('BOX1 RESET '):
            reply = ('BOX1 OK sync=' + command.split()[-1] + '\n').encode()
        elif command.startswith('BOX1 LISTEN '):
            reply = f'BOX1 OK bytes={len(self.recording)} audio=pull1 reason=silence\n'.encode()
        elif command.startswith('BOX1 RECORD '):
            metadata = (f' expected={command[12:]} partial=1 elapsed_ms=12000 error=263'
                        if self.partial_capture else '')
            reply = f'BOX1 OK bytes={len(self.recording)}{metadata} audio=pull1\n'.encode()
        elif command.startswith('BOX1 READ '):
            offset = int(command[10:])
            payload = self.recording[offset:offset + 256]
            checksum = zlib.crc32(payload)
            fault, self.read_fault = self.read_fault, None
            if fault == 'checksum':
                checksum ^= 1
            ack = f'BOX1 OK offset={offset} bytes={len(payload)} crc={checksum:08x}\n'.encode()
            if fault == 'missing_packet':
                payload = payload[64:]
            elif fault == 'truncated_packet':
                payload = payload[:-2]
            lines = [b'BOX1 DATA ' + payload[n:n + 64].hex().encode() + b'\n'
                     for n in range(0, len(payload), 64)]
            if fault == 'malformed':
                lines[0] = b'BOX1 DATA GG\n'
            reply = b''.join(lines) + ack
        else:
            if command.startswith(('BOX1 PLAY ', 'BOX1 STREAM ')):
                self.upload.clear()
            if command.startswith('BOX1 DATA '):
                self.played.extend(bytes.fromhex(command[10:]))
            reply = b'Volume: 0%\nBOX1 OK mic=1 speaker=1 rate=16000 audio=pull1\n'
        self.response.extend(reply)
        return len(data)

    def read(self, size):
        # Arbitrary fragmentation, including within UTF-8 hex and line framing.
        chunk = bytes(self.response[:7])
        del self.response[:7]
        return chunk


class ProtocolTests(unittest.TestCase):
    def test_checked_audio_retry_never_duplicates_committed_samples(self):
        pcm = bytes(range(256)) * 4
        for fault in ('reject_once', 'wrong_ack'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                box = box3.Box3('fake', serial_factory=FakeSerial)
                box.status += ' upload=checked1 rx=4096'
                box.serial.chunk_fault = fault
                path = Path(temp) / 'speech.wav'
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(pcm)
                box.play(path)
                self.assertEqual(bytes(box.serial.played), pcm)
                first = [command for command in box.serial.commands if command.startswith('BOX1 CHUNK 0 ')]
                self.assertEqual(len(first), 2)
                self.assertEqual(first[0], first[1])

    def test_long_track_streams_once_and_retries_without_duplicate_audio(self):
        pcm = bytes(range(256)) * 2501
        self.box.status += ' rx=4096 upload=checked1 stream=ring1'
        self.box.serial.chunk_fault = 'wrong_ack'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'track.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            self.box.play(path)
        self.assertEqual(bytes(self.box.serial.played), pcm)
        self.assertEqual(self.box.serial.commands.count('BOX1 END'), 1)
        self.assertIn(f'BOX1 STREAM {len(pcm)}', self.box.serial.commands)
        self.assertFalse(any(c.startswith('BOX1 PLAY ') for c in self.box.serial.commands))

    def test_stream_buffer_failure_reports_position_and_cancels(self):
        self.box.status += ' rx=4096 upload=checked1 stream=ring1'
        original_command = self.box.command
        def command(packet, **kwargs):
            if packet.startswith('CHUNK 256 '):
                raise RuntimeError('BOX1 ERR chunk_buffer buffer=0 expected=0')
            return original_command(packet, **kwargs)
        self.box.command = command
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'track.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(bytes(1024))
            with self.assertRaisesRegex(RuntimeError, r'chunk_buffer.*offset=256/1024.*streaming=True'):
                self.box.play(path)
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 CANCEL')
        self.assertNotIn('BOX1 END', self.box.serial.commands)

    def test_stream_start_size_mismatch_is_cancelled_before_audio(self):
        self.box.status += ' rx=4096 upload=checked1 stream=ring1'
        self.box.serial.inject = b'BOX1 OK stream=ring1 bytes=2\n'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'track.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(bytes(1024))
            with self.assertRaisesRegex(RuntimeError, 'Stream size mismatch'):
                self.box.play(path)
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 CANCEL')
        self.assertFalse(any(c.startswith('BOX1 CHUNK ') for c in self.box.serial.commands))

    def test_recovery_ignores_old_acks_errors_and_data(self):
        self.box.synchronized = False
        self.box.serial.inject = (b'BOX1 OK next=256\nBOX1 OK\nBOX1 ERR stream_stopped\n'
                                  b'BOX1 DATA 0000\nBOX1 OK sync=wrong\nBOX1 OK sync=barrier\n')
        with patch.object(box3.secrets, 'token_hex', return_value='barrier'):
            self.box.recover()
        self.assertTrue(self.box.synchronized)
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 RESET barrier')
        self.assertIn('mic=1', self.box.command('PING')[1])

    def test_out_of_sync_link_refuses_new_recording(self):
        self.box.synchronized = False
        before = len(self.box.serial.commands)
        with self.assertRaisesRegex(RuntimeError, 'out of sync'):
            self.box.capture(0.1)
        self.assertEqual(len(self.box.serial.commands), before)

    def test_stream_busy_retries_identical_packet_without_duplicate_audio(self):
        self.box.status += ' rx=4096 upload=checked1 stream=ring1'
        original_command = self.box.command
        busy_packets = []
        def command(packet, **kwargs):
            if packet.startswith('CHUNK 256 ') and len(busy_packets) < 4:
                busy_packets.append(packet)
                raise RuntimeError('BOX1 ERR stream_busy next=256 read=0')
            return original_command(packet, **kwargs)
        self.box.command = command
        pcm = bytes(range(256)) * 4
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'track.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            with patch.object(box3.time, 'sleep'):
                self.box.play(path)
        self.assertEqual(len(busy_packets), 4)
        self.assertEqual(len(set(busy_packets)), 1)
        self.assertEqual(bytes(self.box.serial.played), pcm)

    def test_lost_stream_request_or_ack_recovers_without_restarting_track(self):
        pcm = bytes(range(256)) * 2501
        for committed in (False, True):
            with self.subTest(committed=committed), tempfile.TemporaryDirectory() as temp:
                box = box3.Box3('fake', serial_factory=FakeSerial)
                box.status += ' rx=4096 upload=checked1 stream=ring1 sync=1 streamrev=4'
                original_handle = box.serial._handle_packet
                dropped = []
                def handle(data):
                    if data.startswith(b'BOX1 CHUNK 320000 ') and not dropped:
                        dropped.append(data)
                        if committed:
                            original_handle(data)
                            box.serial.response.clear()
                        return len(data)
                    return original_handle(data)
                box.serial._handle_packet = handle
                clock = [0.0]
                def now():
                    clock[0] += 0.01
                    return clock[0]
                path = Path(temp) / 'track.wav'
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(pcm)
                progress = Mock()
                with patch.object(box3.time, 'monotonic', side_effect=now):
                    box.play(path, progress=progress)
                self.assertEqual(len(dropped), 1)
                self.assertEqual(bytes(box.serial.played), pcm)
                self.assertEqual(box.serial.commands.count('BOX1 END'), 1)
                self.assertEqual(sum(c.startswith('BOX1 STREAM ') for c in box.serial.commands), 1)
                self.assertTrue(any(c.startswith('BOX1 SYNC ') for c in box.serial.commands))
                self.assertFalse(any(c.startswith('BOX1 RESET ') for c in box.serial.commands))
                self.assertTrue(box.synchronized)
                self.assertLess(max(box.serial.write_sizes), 512)
                self.assertTrue(any('USB reply recovered' in c.args[0] for c in progress.call_args_list))

    def test_expression_is_capability_gated_and_validated(self):
        before = len(self.box.serial.commands)
        self.box.expression('happy')
        self.assertEqual(len(self.box.serial.commands), before)
        self.box.status += ' face=1'
        self.box.expression('music')
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 FACE music')
        with self.assertRaises(ValueError):
            self.box.expression('invalid\nCANCEL')

    def test_pause_capture_downloads_variable_length_audio(self):
        self.box.status += ' vad=1'
        self.box.serial.recording = bytes(range(256)) * 8
        self.assertEqual(self.box.capture_speech(80, 0.8), self.box.serial.recording)
        self.assertIn('BOX1 LISTEN 80 800 2000', self.box.serial.commands)

    def test_pause_capture_returns_silence_without_downloading(self):
        self.box.status += ' vad=1'
        self.box.serial.inject = b'BOX1 OK bytes=0 audio=pull1 reason=silence\n'
        before = len(self.box.serial.commands)
        self.assertEqual(self.box.capture_speech(), b'')
        self.assertEqual(len(self.box.serial.commands) - before, 1)

    def test_pause_capture_requires_new_firmware(self):
        with self.assertRaisesRegex(RuntimeError, 'vad=1'):
            self.box.capture_speech()

    def test_audio_upload_fits_legacy_256_byte_receive_queue(self):
        box = box3.Box3('fake', serial_factory=FakeSerial)
        box.serial.rx_capacity = 256
        pcm = bytes(range(256)) * 4
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'tone.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            box.play(path)
        self.assertEqual(bytes(box.serial.played), pcm)
        self.assertLessEqual(max(box.serial.write_sizes), 256)

    def test_long_text_is_paced_for_legacy_receive_queue(self):
        self.box.serial.rx_capacity = 256
        text = '\u4E2D\u6587' * 100
        self.box.display(text, 'zh')
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 TEXT zh ' + text.encode().hex())
        self.assertLessEqual(max(self.box.serial.write_sizes), 256)

    def setUp(self):
        self.box = box3.Box3('fake', serial_factory=FakeSerial)

    def test_multilingual_text_and_emoji(self):
        text = '\u4E2D\u6587 \U0001F916'
        self.box.display(text, 'zh')
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 TEXT zh ' + text.encode().hex())

    def test_text_limits(self):
        for text in ('a' * 1025, 'a\0b'):
            with self.assertRaises(ValueError):
                self.box.display(text)
        with self.assertRaises(ValueError):
            self.box.display('hello', 'invalid')

    def test_record_and_play_signed_pcm(self):
        # Use a valid 0.1 second capture, including signed boundary values.
        self.box.serial.recording *= 534
        self.box.serial.recording = self.box.serial.recording[:3200]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'audio.wav'
            self.box.record(path, 0.1)
            with wave.open(str(path), 'rb') as wav:
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.readframes(1600), self.box.serial.recording)
            progress = Mock()
            self.box.status += ' rx=4096 upload=checked1'
            self.box.play(path, progress=progress)
            self.assertEqual(bytes(self.box.serial.played), self.box.serial.recording)
            self.assertGreater(max(self.box.serial.write_sizes), 256)
            messages = [call.args[0] for call in progress.call_args_list]
            self.assertEqual(messages[0], 'Uploading audio: 0%')
            self.assertIn('Playing on BOX-3 speaker...', messages)
            self.assertEqual(messages[-1], 'Playback complete')

    def test_unavailable_speaker_is_reported_before_upload(self):
        self.box.status = 'BOX1 OK mic=1 speaker=0'
        with self.assertRaisesRegex(RuntimeError, 'speaker codec initialization failed'):
            self.box.play('unused.wav')

    def test_device_error_and_oversized_audio(self):
        self.box.serial.inject = b'BOX1 ERR memory\n'
        with self.assertRaisesRegex(RuntimeError, 'memory'):
            self.box.command('PING')
        self.box.serial.inject = b'BOX1 DATA 00000000\nBOX1 OK\n'
        with self.assertRaisesRegex(RuntimeError, 'oversized'):
            self.box.command('RECORD 2', max_data=2)

    def test_wrong_wave_format(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'wrong.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                wav.writeframes(b'\0' * 16)
            with self.assertRaisesRegex(ValueError, '16000'):
                self.box.play(path)

    def test_malformed_audio_drains_response_before_next_command(self):
        self.box.serial.inject = b'BOX1 DATA 01ZZ\r\nBOX1 DATA 0000\nBOX1 OK\n'
        with self.assertRaisesRegex(RuntimeError, 'Malformed audio response.*01ZZ'):
            self.box.command('RECORD 4', max_data=4)
        _, status = self.box.command('PING')
        self.assertIn('mic=1 speaker=1', status)

    def test_full_audio_packet_with_crlf_and_fragmentation(self):
        payload = bytes(range(256)) * 2
        self.box.serial.inject = b'BOX1 DATA ' + payload.hex().encode() + b'\r\nBOX1 OK\r\n'
        actual, _ = self.box.command('RECORD 512', max_data=512)
        self.assertEqual(actual, payload)

    def test_duration_limits(self):
        for duration in (0, 11, float('nan')):
            with self.assertRaises(ValueError):
                self.box.record('unused.wav', duration)

    def test_missing_or_corrupted_block_is_retried_by_offset(self):
        for fault in ('missing_packet', 'truncated_packet', 'checksum', 'malformed'):
            with self.subTest(fault=fault):
                self.box.serial.recording = bytes(range(256)) * 12 + bytes(128)
                self.box.serial.read_fault = fault
                before = self.box.serial.commands.count('BOX1 READ 0')
                result = self.box.capture(0.1)
                self.assertEqual(result, self.box.serial.recording)
                self.assertEqual(self.box.serial.commands.count('BOX1 READ 0') - before, 2)

    def test_old_firmware_rejected_before_recording(self):
        self.box.status = 'BOX1 OK mic=1 speaker=1 rate=16000'
        with self.assertRaisesRegex(RuntimeError, 'Upload the current firmware'):
            self.box.capture(0.1)

    def test_wrong_recording_length_reports_counts(self):
        with self.assertRaisesRegex(RuntimeError, 'expected 3200 bytes'):
            self.box.capture(0.1)

    def test_partial_recording_is_saved_but_reported_as_failure(self):
        self.box.serial.recording = struct.pack('<h', -500) * 800
        self.box.serial.partial_capture = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'partial.wav'
            with self.assertRaisesRegex(RuntimeError, 'captured 1600/3200 bytes.*Partial WAV saved'):
                self.box.record(path, 0.1)
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getnframes(), 800)
                self.assertEqual(wav.readframes(800), self.box.serial.recording)

    def test_recognition_capture_remains_strict_on_partial_audio(self):
        self.box.serial.recording = bytes(1600)
        self.box.serial.partial_capture = True
        with self.assertRaises(box3.IncompleteRecording) as caught:
            self.box.capture(0.1)
        self.assertEqual(caught.exception.audio, bytes(1600))
        self.assertEqual(self.box.serial.commands[-1], 'BOX1 CANCEL')


if __name__ == '__main__':
    unittest.main()
