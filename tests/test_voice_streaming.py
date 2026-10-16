"""Failure boundaries, true producer/playback overlap, and persistent connections."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import wave
import zlib
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
import voice_stream as stream
import chat_backends as chat
import streaming_reply as pipeline
import offline_speech as speech
from box3 import Box3


def wire(*events):
    return io.BytesIO(b''.join(('data: '+(e if isinstance(e, str) else json.dumps(e))+'\r\n\r\n').encode() for e in events))


class VoiceStreamingTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'OPENAI_API_KEY': 'api-secret', 'GEMINI_API_KEY': 'gemini-secret',
                                     'OPENCLAW_GATEWAY_TOKEN': 'gateway-secret'}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_multiline_sse_and_truncation(self):
        self.assertEqual(list(stream.sse_events(io.BytesIO(b': ping\n\ndata: first\r\ndata:second\r\n\r\n'))), ['first\nsecond'])
        for data in (b'data: truncated', b'data: truncated\n', b'data: '+b'x'*32769+b'\n\n'):
            with self.subTest(data=data[:20]), self.assertRaises(RuntimeError):
                list(stream.sse_events(io.BytesIO(data)))

    def test_sentence_splitter_keeps_decimal_and_cjk(self):
        splitter = stream.Sentences()
        out = []
        for char in '溫度3.14。Next sentence. 最後です！Tail':
            out.extend(splitter.feed(char))
        out.extend(splitter.finish())
        self.assertEqual(out, ['溫度3.14。', 'Next sentence.', '最後です！', 'Tail'])

    def test_all_providers_emit_before_completion_and_commit_complete_turn(self):
        cases = {
            'openai': [{'type': 'response.output_text.delta', 'delta': 'Hello.'},
                       {'type': 'response.completed', 'response': {'status': 'completed'}}],
            'openclaw': [{'choices': [{'delta': {'content': 'Hello.'}, 'finish_reason': None}]},
                         {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}, '[DONE]'],
            'gemini': [{'candidates': [{'content': {'parts': [{'text': 'Hello.'}]}}]},
                       {'candidates': [{'finishReason': 'STOP'}]}]}
        for provider, events in cases.items():
            backend = chat.CloudChat(provider, 'openclaw/default' if provider == 'openclaw' else 'test')
            received = []
            def delta(text):
                self.assertEqual(backend.history, [])
                received.append(text)
            with self.subTest(provider=provider), patch.object(backend.http, 'post', return_value=wire(*events)) as post:
                self.assertEqual(backend.ask('Hello', on_delta=delta), 'Hello.')
                self.assertEqual(received, ['Hello.'])
                self.assertEqual(len(backend.history), 2)
                if provider == 'openclaw':
                    self.assertEqual(post.call_args.args[2]['Authorization'], 'Bearer gateway-secret')
                if provider == 'gemini':
                    self.assertIn(':streamGenerateContent?alt=sse', post.call_args.args[0])

    def test_incomplete_failed_and_tool_streams_do_not_commit_history(self):
        cases = [('openai', [{'type': 'response.output_text.delta', 'delta': 'Partial.'}]),
                 ('openai', [{'type': 'response.failed'}]),
                 ('gemini', [{'candidates': [{'finishReason': 'SAFETY'}]}]),
                 ('openclaw', [{'choices': [{'finish_reason': 'stop', 'delta': {'content': 'Partial'}}]}]),
                 ('openclaw', [{'choices': [{'delta': {'tool_calls': [{'id': 'call'}]}}]}])]
        for provider, events in cases:
            backend = chat.CloudChat(provider, 'openclaw/default' if provider == 'openclaw' else 'test')
            with self.subTest(provider=provider, events=events), patch.object(backend.http, 'post', return_value=wire(*events)), self.assertRaises(RuntimeError):
                backend.ask('Hello', on_delta=lambda _: None)
            self.assertEqual(backend.history, [])

    def test_http_reuses_origin_and_refuses_redirect(self):
        response = Mock(status=200)
        response.getheader.return_value = 'text/event-stream'
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(stream.http.client, 'HTTPConnection', return_value=connection) as create:
            client = stream.PersistentHTTP()
            client.post('http://localhost:18789/v1/chat/completions', {}, {'Authorization': 'Bearer secret'})
            client.post('http://localhost:18789/v1/chat/completions', {}, {'Authorization': 'Bearer secret'})
            create.assert_called_once()
            response.status = 302
            with self.assertRaisesRegex(RuntimeError, '302'):
                client.post('http://localhost:18789/v1/chat/completions', {}, {})
            self.assertIsNone(client.connection)

    def test_first_sentence_plays_while_model_still_generates(self):
        played = threading.Event()
        class Backend:
            def ask(self, text, on_delta):
                on_delta('第一句。')
                if not played.wait(3):
                    raise RuntimeError('Playback did not overlap generation')
                on_delta('第二句。')
                return '第一句。第二句。'
        def synthesize(text, output, language):
            with wave.open(str(output), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(bytes(320))
        box = Mock()
        def play(path, progress):
            played.set()
            progress('Streaming')
            self.assertTrue(path.exists())
        box.play.side_effect = play
        with tempfile.TemporaryDirectory() as temp, patch.object(pipeline, 'synthesize_resident', side_effect=synthesize):
            result = pipeline.stream_reply(box, Backend(), 'Hi', temp, 'Test', lambda _: 'zh-TW', lambda text, _: [text])
        self.assertEqual(result, '第一句。第二句。')
        self.assertEqual(box.play.call_count, 2)

    def test_synthesis_error_stops_producers_and_never_plays(self):
        class Backend:
            def ask(self, text, on_delta):
                on_delta('Sentence. ')
                return 'Sentence.'
        box = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.object(pipeline, 'synthesize_resident', side_effect=RuntimeError('voice missing')):
            with self.assertRaisesRegex(RuntimeError, 'voice missing'):
                pipeline.stream_reply(box, Backend(), 'Hi', temp, 'Test', lambda _: 'en', lambda text, _: [text])
        box.play.assert_not_called()

    def test_wifi_push_capture_checks_crc_and_avoids_pull_commands(self):
        box = Box3.__new__(Box3)
        box.status = 'BOX1 OK vad=1 listenstream=1'
        box.stream_capture = True
        box.serial = Mock(port='socket://device:8233')
        pcm = b'\x01\x00'*320
        box.command = Mock(return_value=(pcm, f'BOX1 OK bytes={len(pcm)} audio=push1 crc={zlib.crc32(pcm):08x} reason=silence'))
        self.assertEqual(box.capture_speech(), pcm)
        box.command.assert_called_once_with('LISTENSTREAM 80 600 2000', max_data=320000)
        box.command.return_value = (pcm, f'BOX1 OK bytes={len(pcm)} audio=push1 crc=00000000')
        with self.assertRaisesRegex(RuntimeError, 'CRC'):
            box.capture_speech()

    def test_resident_piper_loads_once_for_two_sentences(self):
        speech._piper_voices.clear()
        def render(text, wav):
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(bytes(320))
        voice = Mock()
        voice.synthesize_wav.side_effect = render
        def convert(source, destination):
            destination.write_bytes(source.read_bytes())
        with tempfile.TemporaryDirectory() as temp, patch('piper.PiperVoice.load', return_value=voice) as load, \
                patch.object(speech, 'model_path', return_value=Path(temp)/'voice.onnx'), \
                patch.object(speech, 'convert_audio', side_effect=convert):
            speech.synthesize_resident('First sentence.', Path(temp)/'1.wav', 'en')
            speech.synthesize_resident('Second sentence.', Path(temp)/'2.wav', 'en')
            load.assert_called_once()
            self.assertEqual(voice.synthesize_wav.call_count, 2)
        speech._piper_voices.clear()

    def test_resident_resamples_pcm_without_ffmpeg(self):
        import struct
        speech._piper_voices.clear()
        def render(text, wav):
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(struct.pack('<h', 1234)*240)
        voice = Mock()
        voice.synthesize_wav.side_effect = render
        with tempfile.TemporaryDirectory() as temp, patch('piper.PiperVoice.load', return_value=voice), \
                patch.object(speech, 'model_path', return_value=Path(temp)/'voice.onnx'), \
                patch.object(speech, 'convert_audio') as ffmpeg:
            output = Path(temp)/'reply.wav'
            speech.synthesize_resident('Hello.', output, 'en')
            ffmpeg.assert_not_called()
            with wave.open(str(output), 'rb') as wav:
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.getnframes(), 160)
                self.assertEqual(wav.readframes(160), struct.pack('<h', 1234)*160)
        speech._piper_voices.clear()

    def test_failure_cancels_a_network_producer_before_joining(self):
        stopped = threading.Event()
        class Backend:
            def ask(self, text, on_delta):
                on_delta('First sentence. ')
                if not stopped.wait(3):
                    raise RuntimeError('Producer cancellation was not delivered')
                raise RuntimeError('Cancelled')
            def cancel(self):
                stopped.set()
        with tempfile.TemporaryDirectory() as temp, patch.object(pipeline, 'synthesize_resident', side_effect=RuntimeError('synthesis failed')):
            with self.assertRaisesRegex(RuntimeError, 'synthesis failed'):
                pipeline.stream_reply(Mock(), Backend(), 'Hi', temp, 'Test', lambda _: 'en', lambda text, _: [text])
        self.assertTrue(stopped.is_set())

    def test_sse_has_a_total_deadline_even_with_keepalives(self):
        with patch.object(stream.time, 'monotonic', side_effect=[0, 91]), self.assertRaisesRegex(RuntimeError, 'time limit'):
            list(stream.sse_events(io.BytesIO(b': keepalive\n\n')))


    def test_default_capture_uses_stable_listen_even_if_stream_is_advertised(self):
        box = Box3.__new__(Box3)
        box.status = 'BOX1 OK vad=1 listenstream=1'
        box.serial = Mock(port='socket://device:8233')
        box.command = Mock(return_value=(b'', 'BOX1 OK bytes=2 audio=pull1 reason=silence'))
        box._pull_recording = Mock(return_value=b'\x01\x00')
        self.assertEqual(box.capture_speech(), b'\x01\x00')
        box.command.assert_called_once_with('LISTEN 80 600 2000')
        box._pull_recording.assert_called_once()

    def test_first_long_chinese_clause_is_released_before_answer_completes(self):
        splitter = stream.Sentences()
        clause = '現在這個地區的天氣狀況是多雲而且溫度大約攝氏十三度，'
        self.assertEqual(list(splitter.feed(clause)), [clause])
        self.assertEqual(list(splitter.feed('接下來補充細節，還沒結束')), [])
        self.assertEqual(list(splitter.finish()), ['接下來補充細節，還沒結束'])

    def test_warmup_loads_both_voices_once_without_speaking(self):
        speech._piper_voices.clear()
        voice = Mock()
        def render(text, wav):
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(bytes(320))
        voice.synthesize_wav.side_effect = render
        with tempfile.TemporaryDirectory() as temp, patch('piper.PiperVoice.load', return_value=voice) as load, \
             patch.object(speech, 'model_path', side_effect=lambda _, lang: Path(temp)/(lang+'.onnx')):
            speech.warmup_resident(('zh-TW', 'en'))
            self.assertEqual(load.call_count, 2)
            voice.synthesize_wav.assert_not_called()
            speech.synthesize_resident('你好 hello', Path(temp)/'reply.wav', 'zh-TW')
            self.assertEqual(load.call_count, 2)
            self.assertEqual(voice.synthesize_wav.call_count, 2)
        speech._piper_voices.clear()
