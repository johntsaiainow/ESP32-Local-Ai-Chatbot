"""Input failures must not terminate the host and release its TCP controller."""
import io
from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1]/'host'))
import voice_agent as voice
from box3 import Box3Connection

class VoiceReconnectTests(unittest.TestCase):
    def test_listen_timeout_reconnects_then_accepts_quit(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, '/quit']
        box = Mock(status='BOX1 OK', synchronized=True)
        with patch.object(sys, 'argv', ['voice_agent.py', '--host', '192.168.1.2', '--no-wake-word']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), \
             patch.object(voice, 'create_recognizer', return_value=Mock(language='auto')), \
             patch.object(voice, 'PiRPC'), \
             patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', side_effect=TimeoutError('did not respond to LISTENSTREAM')), \
             patch.object(voice, 'ask_pi') as pi, \
             patch('sys.stdout', io.StringIO()) as out, patch('sys.stderr', io.StringIO()) as err:
            voice.main()
        box.reconnect.assert_called_once()
        box.close.assert_called_once()
        pi.assert_not_called()
        self.assertIn('LISTENSTREAM', err.getvalue())
        self.assertIn('failed utterance was discarded', out.getvalue())

    def test_reconnect_uses_same_transport_without_replaying_requests(self):
        devices = []
        def factory(endpoint):
            device = Mock(status='BOX1 OK link=1')
            devices.append(device)
            return device
        with patch('box3.time.sleep'):
            box = Box3Connection({'wifi': 'socket://device:8233', 'usb': '/dev/usb'}, 'wifi', factory)
            box.reconnect()
        self.assertEqual(box.active, 'wifi')
        devices[0].close.assert_called_once()
        self.assertIs(box.device, devices[1])
        self.assertFalse(devices[1].stream_capture)
        commands = [call.args[0] for call in devices[1].command.call_args_list]
        self.assertEqual(commands, ['LINK SET WIFI', 'LINK OPTIONS 1 1'])
