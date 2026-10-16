"""Verify persistent Pi integration and explicit compatibility opt-out."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1]/'host'))
import voice_agent as voice

class PiRPCVoiceTests(unittest.TestCase):
    def run_host(self, extra):
        commands=Mock()
        commands.get.side_effect=['Hello','Next question','/quit']
        rpc=Mock()
        box=Mock(status='BOX1 OK')
        with patch.object(sys, 'argv', ['voice_agent.py','--host','192.168.1.2','--keyboard-only',*extra]), \
             patch.object(voice.queue,'Queue',return_value=commands), \
             patch.object(voice.threading,'Thread'), \
             patch.object(voice,'PiRPC',return_value=rpc) as factory, \
             patch.object(voice,'Box3Connection',return_value=box), \
             patch.object(voice,'stream_reply') as stream, \
             patch.object(voice,'ask_pi',return_value='Reply') as ask, \
             patch.object(voice,'speak_reply'), patch('sys.stdout',io.StringIO()):
            voice.main()
        return rpc, factory, stream, ask

    def test_two_requests_reuse_one_started_rpc_and_close_on_exit(self):
        rpc,factory,stream,ask=self.run_host([])
        factory.assert_called_once()
        rpc.start.assert_called_once()
        rpc.close.assert_called_once()
        self.assertEqual(stream.call_count,2)
        for call in stream.call_args_list:
            self.assertIs(call.args[1],rpc)
        ask.assert_not_called()

    def test_no_stream_replies_keeps_original_cli_path(self):
        rpc,factory,stream,ask=self.run_host(['--no-stream-replies'])
        factory.assert_not_called()
        stream.assert_not_called()
        self.assertEqual(ask.call_count,2)
