"""OpenClaw routing and credential isolation, without live Gateway calls."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
import chat_backends as chat

class OpenClawTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'OPENCLAW_GATEWAY_TOKEN': 'gateway-secret',
                         'OPENCLAW_GATEWAY_URL': 'http://192.168.1.2:18789'}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_endpoint_validation(self):
        self.assertEqual(chat.openclaw_endpoint('https://gateway.example/v1/'),
                         'https://gateway.example/v1/chat/completions')
        for base in ('ftp://host', 'http://u:p@host', 'http://host?token=x',
                     'http://host#x', 'http://@host', 'http://host/other', 'http://host:65536', 'http://host\r\n'):
            with self.subTest(base=base), self.assertRaises(ValueError):
                chat.openclaw_endpoint(base)

    def test_gateway_payload_and_history_without_openai_key(self):
        backend = chat.CloudChat('openclaw')
        self.assertEqual(backend.model, 'openclaw/default')
        def respond(request, timeout):
            self.assertEqual(request.full_url, 'http://192.168.1.2:18789/v1/chat/completions')
            self.assertEqual(request.get_header('Authorization'), 'Bearer gateway-secret')
            payload = json.loads(request.data)
            self.assertEqual(payload['model'], 'openclaw/default')
            self.assertFalse(payload['stream'])
            self.assertNotIn('user', payload)
            self.assertEqual(payload['messages'][-1], {'role': 'user', 'content': '你好'})
            self.assertNotIn('no tools', payload['messages'][0]['content'])
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': '你好！'}}]}).encode())
        opener = Mock()
        opener.open.side_effect = respond
        with patch.object(chat, 'build_opener', return_value=opener), patch.object(chat, 'urlopen') as cloud:
            self.assertEqual(backend.ask('你好'), '你好！')
            cloud.assert_not_called()
        self.assertEqual(len(backend.history), 2)

    def test_failed_gateway_response_does_not_commit_history(self):
        for data in ({}, {'choices': [None]}, {'choices': [{'finish_reason': 'tool_calls'}]},
                     {'choices': [{'finish_reason': 'stop', 'message': {'content': ''}}]}):
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps(data).encode())
            backend = chat.CloudChat('openclaw')
            with patch.object(chat, 'build_opener', return_value=opener), self.assertRaises(RuntimeError):
                backend.ask('Hello')
            self.assertEqual(backend.history, [])

    def test_redirects_are_refused_and_secrets_not_disclosed(self):
        self.assertIsNone(chat.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other'))
        opener = Mock()
        opener.open.side_effect = HTTPError('http://host', 401, 'gateway-secret', {}, None)
        with patch.object(chat, 'build_opener', return_value=opener), self.assertRaises(RuntimeError) as caught:
            chat.CloudChat('openclaw').ask('Hello')
        self.assertIn('401', str(caught.exception))
        self.assertNotIn('gateway-secret', str(caught.exception))

    def test_configuration_requires_gateway_secret_and_agent_target(self):
        with self.assertRaises(ValueError):
            chat.CloudChat('openclaw', 'gpt-model')
        with patch.dict(os.environ, {'OPENCLAW_GATEWAY_TOKEN': ''}), self.assertRaisesRegex(ValueError, 'OPENCLAW_GATEWAY_TOKEN'):
            chat.CloudChat('openclaw')

    def test_voice_cli_routes_openclaw_without_pi(self):
        import voice_agent as voice
        queue = Mock()
        queue.get.side_effect = ['Hello', '/quit']
        backend = Mock(model='openclaw/default')
        backend.ask.return_value = 'Gateway reply'
        box = Mock(status='BOX1 OK')
        with patch.object(sys, 'argv', ['voice_agent.py', '--port', 'fake', '--keyboard-only',
                                      '--provider', 'openclaw']), \
                patch.object(voice.queue, 'Queue', return_value=queue), \
                patch.object(voice.threading, 'Thread'), \
                patch.object(voice, 'CloudChat', return_value=backend), \
                patch.object(voice, 'Box3Connection', return_value=box), \
                patch.object(voice, 'ask_pi') as pi, \
                patch.object(voice, 'speak_reply') as speak, patch('sys.stdout', io.StringIO()):
            voice.main()
        backend.ask.assert_called_once_with('Hello')
        pi.assert_not_called()
        self.assertEqual(speak.call_args.args[3], 'OpenClaw')
        box.close.assert_called_once()
