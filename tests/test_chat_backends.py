"""Cloud provider payloads, conversation state, and failures without live API calls."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
import chat_backends as chat
import voice_agent as voice


def openai_reply(text='Hello'):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}]}]}


class CloudBackendTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'OPENAI_API_KEY': 'test-openai-secret',
                                                   'GEMINI_API_KEY': 'test-gemini-secret'}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def respond(self, data):
        return patch.object(chat, 'urlopen', return_value=io.BytesIO(json.dumps(data).encode()))

    def test_configuration_errors_happen_before_network_requests(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                chat.CloudChat('openai', 'test-model')
        with self.assertRaisesRegex(ValueError, 'Choose a model'):
            chat.CloudChat('gemini')
        with self.assertRaises(ValueError):
            chat.CloudChat('unknown')

    def test_environment_model_and_explicit_override(self):
        with patch.dict(os.environ, {'BOX3_OPENAI_MODEL': 'env-model'}):
            self.assertEqual(chat.CloudChat('openai').model, 'env-model')
            self.assertEqual(chat.CloudChat('openai', 'explicit').model, 'explicit')

    def test_openai_request_and_multi_turn_history(self):
        backend = chat.CloudChat('openai', 'test-model')
        with self.respond(openai_reply('你好')) as request:
            self.assertEqual(backend.ask('Hello'), '你好')
        call = request.call_args.args[0]
        self.assertEqual(call.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(call.get_header('Authorization'), 'Bearer test-openai-secret')
        body = json.loads(call.data)
        self.assertFalse(body['store'])
        self.assertEqual(body['input'], [{'role': 'user', 'content': 'Hello'}])
        with self.respond(openai_reply('Again')) as request:
            backend.ask('Follow up')
        history = json.loads(request.call_args.args[0].data)['input']
        self.assertEqual([item['role'] for item in history], ['user', 'assistant', 'user'])
        self.assertEqual(history[1]['content'], '你好')

    def test_gemini_headers_roles_and_excludes_thought_parts(self):
        backend = chat.CloudChat('gemini', 'test-model')
        data = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
            {'text': 'internal reasoning', 'thought': True}, {'text': 'Hello'}]}}]}
        with self.respond(data) as request:
            self.assertEqual(backend.ask('Hi'), 'Hello')
        call = request.call_args.args[0]
        self.assertNotIn('test-gemini-secret', call.full_url)
        self.assertEqual(call.get_header('X-goog-api-key'), 'test-gemini-secret')
        with self.respond(data) as request:
            backend.ask('Again')
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual([item['role'] for item in body['contents']], ['user', 'model', 'user'])
        self.assertIn('systemInstruction', body)

    def test_empty_blocked_and_incomplete_responses_do_not_commit_history(self):
        for provider, data in [('openai', {'output': []}),
                               ('openai', {'status': 'incomplete'}),
                               ('gemini', {'candidates': []}),
                               ('gemini', {'candidates': [{'finishReason': 'SAFETY'}]})]:
            with self.subTest(provider=provider, data=data):
                backend = chat.CloudChat(provider, 'test-model')
                with self.respond(data), self.assertRaises(RuntimeError):
                    backend.ask('Hello')
                self.assertEqual(backend.history, [])

    def test_http_error_does_not_disclose_key_or_response_body(self):
        backend = chat.CloudChat('openai', 'test-model')
        error = HTTPError('https://api.openai.com/v1/responses', 401, 'test-openai-secret', {}, None)
        with patch.object(chat, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                backend.ask('Hello')
        self.assertIn('401', str(caught.exception))
        self.assertNotIn('test-openai-secret', str(caught.exception))
        self.assertEqual(backend.history, [])

    def test_network_error_is_actionable_and_does_not_commit_history(self):
        backend = chat.CloudChat('gemini', 'test-model')
        with patch.object(chat, 'urlopen', side_effect=URLError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'internet access'):
                backend.ask('Hello')
        self.assertEqual(backend.history, [])

    def test_history_is_bounded_to_complete_turns(self):
        backend = chat.CloudChat('openai', 'test-model')
        for index in range(15):
            with self.respond(openai_reply()):
                backend.ask(str(index))
        self.assertEqual(len(backend.history), 24)
        self.assertEqual(backend.history[0], {'role': 'user', 'content': '3'})

    def test_cloud_selection_routes_without_pi_cli(self):
        queue = Mock()
        queue.get.side_effect = ['Hello', '/quit']
        cloud = Mock(model='test-model')
        cloud.ask.return_value = 'Cloud reply'
        box = Mock(status='BOX1 OK')
        with patch.object(sys, 'argv', ['voice_agent.py', '--port', 'fake', '--keyboard-only',
                                       '--provider', 'openai', '--model', 'test-model']), \
                patch.object(voice.queue, 'Queue', return_value=queue), \
                patch.object(voice.threading, 'Thread'), \
                patch.object(voice, 'CloudChat', return_value=cloud), \
                patch.object(voice, 'Box3Connection', return_value=box), \
                patch.object(voice, 'ask_pi') as pi, \
                patch.object(voice, 'speak_reply') as speak, \
                patch('sys.stdout', io.StringIO()):
            voice.main()
        cloud.ask.assert_called_once_with('Hello')
        pi.assert_not_called()
        self.assertEqual(speak.call_args.args[1], 'Cloud reply')
        self.assertEqual(speak.call_args.args[3], 'OpenAI')
        box.close.assert_called_once()
