"""Input failures must not terminate the host and release its TCP controller."""
import io
from pathlib import Path
import queue
import struct
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1]/'host'))
import voice_agent as voice
from box3 import Box3, Box3Connection, scale_playback

class VoiceReconnectTests(unittest.TestCase):
    def test_chinese_microphone_phrases_match_only_complete_requests(self):
        for text, command in [('把麥克風關掉', 'off'), ('请关闭麦克风。', 'off'),
                              ('打開麥克風', 'on'), ('恢复收音', 'on'), ('麥克風狀態？', 'status')]:
            self.assertEqual(voice.chinese_microphone_command(text), '/mic ' + command)
        for text in ('不要把麥克風關掉', '為什麼關閉麥克風', '如何打開麥克風', ''):
            self.assertIsNone(voice.chinese_microphone_command(text))

    def test_chinese_mic_off_stops_capture_and_console_can_restore_it(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, '/quit']
        commands.get.side_effect = [queue.Empty, '打開麥克風']
        box = Mock(status='BOX1 OK face=1 emojistates=1', synchronized=True)
        box.reply_fields = Box3.reply_fields
        box.expression.side_effect = lambda state: Box3.expression(box, state)
        with patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--port', '/dev/test', '--no-wake-word']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), \
             patch.object(voice, 'create_recognizer', return_value=Mock(language='auto')), \
             patch.object(voice, 'PiRPC') as pi, \
             patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', return_value='把麥克風關掉') as listen, \
             patch('sys.stdout', io.StringIO()) as output:
            voice.main()
        listen.assert_called_once()
        self.assertEqual(commands.get.call_count, 2)
        pi.return_value.ask.assert_not_called()
        box.capture.assert_not_called()
        box.reconnect.assert_not_called()
        self.assertIn((('sleeping',), {}), box.expression.call_args_list)
        self.assertIn('Microphone: OFF', output.getvalue())
        self.assertIn('Microphone: ON', output.getvalue())

    def test_environment_reply_and_missing_sensor(self):
        box = Box3.__new__(Box3)
        box.status = 'BOX1 OK environment=1'
        box.command = Mock(return_value=(b'', 'BOX1 OK temperature_c=25.25 humidity_pct=63.50'))
        self.assertEqual(box.environment(), (25.25, 63.5))
        box.command.assert_called_once_with('SENSOR')
        for reply in ('BOX1 OK', 'BOX1 OK temperature_c=nan humidity_pct=50',
                      'BOX1 OK temperature_c=20 humidity_pct=110'):
            box.command.return_value = (b'', reply)
            with self.assertRaises(ValueError):
                box.environment()
        box.command.side_effect = RuntimeError('sensor_missing')
        with self.assertRaisesRegex(ValueError, 'dock'):
            box.environment()
        box.status = 'BOX1 OK'
        box.command.reset_mock()
        with self.assertRaisesRegex(ValueError, 'updated BOX-3 firmware'):
            box.environment()
        box.command.assert_not_called()

    def test_environment_queries_and_normal_conversation(self):
        for text in ('現在幾度？', '湿度多少', '請查詢溫濕度。', '現在溫度多少?', '/sensor'):
            self.assertTrue(voice.environment_query(text), text)
        for text in ('明天天氣幾度', '為什麼濕度很高', '溫度感測器是什麼'):
            self.assertFalse(voice.environment_query(text), text)

    def test_spoken_sensor_query_uses_device_without_pi(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, '/quit']
        box = Mock(status='BOX1 OK', synchronized=True)
        box.environment.return_value = (24.5, 60)
        with patch.object(sys, 'argv', ['voice_agent.py', '--port', '/dev/test', '--no-wake-word']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), \
             patch.object(voice, 'create_recognizer', return_value=Mock(language='auto')), \
             patch.object(voice, 'PiRPC') as pi, \
             patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', return_value='現在幾度？'), \
             patch.object(voice, 'speak_reply') as speak, \
             patch('sys.stdout', io.StringIO()):
            voice.main()
        box.environment.assert_called_once()
        self.assertIn('24.5', speak.call_args.args[1])
        self.assertIn('60.0', speak.call_args.args[1])
        pi.return_value.ask.assert_not_called()

    def test_volume_phrases_are_complete_commands(self):
        for phrase, target in [('大聲一點。', 'up'), ('请小声一点！', 'down'),
                               ('請調高音量', 'up'), ('音量调低', 'down'),
                               ('靜音', '0'), ('目前音量？', 'status'),
                               ('volume down', 'down'), ('turn the volume down', 'down'),
                               ('volume up', 'up'), ('mute', '0'), ('volume status', 'status')]:
            with self.subTest(phrase=phrase):
                self.assertEqual(voice.volume_command(phrase), '/volume ' + target)
        for phrase in ('為什麼要大聲一點？', '不要靜音', '說明音量調低的意思',
                       'why is the volume down', '/volume down', ''):
            self.assertIsNone(voice.volume_command(phrase))

    def test_recognized_volume_is_handled_without_pi(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, '/quit']
        box = Mock(status='BOX1 OK face=1 emojistates=1', synchronized=True, playback_volume=60)
        box.reply_fields = Box3.reply_fields
        box.expression.side_effect = lambda state: Box3.expression(box, state)
        with patch.object(sys, 'argv', ['voice_agent.py', '--port', '/dev/test', '--no-wake-word']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), \
             patch.object(voice, 'create_recognizer', return_value=Mock(language='auto')), \
             patch.object(voice, 'PiRPC') as pi, \
             patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', return_value='volume down'), \
             patch('sys.stdout', io.StringIO()):
            voice.main()
        box.set_volume.assert_called_once_with(50)
        box.reconnect.assert_not_called()
        pi.return_value.ask.assert_not_called()
        box.capture.assert_not_called()

    def test_volume_commands_and_reconnection_preserve_level(self):
        box = Box3Connection({'usb': '/dev/test'}, 'usb',
                             factory=lambda endpoint: Mock(status='BOX1 OK'))
        with patch('sys.stdout', io.StringIO()) as output:
            for command in ('/volume down', '/volume up', '/volume 40', '/volume status'):
                voice.handle_volume_command(box, command)
            self.assertIn('Playback volume: 40%', output.getvalue())
            for command in ('/volume -1', '/volume 101', '/volume bad'):
                voice.handle_volume_command(box, command)
            self.assertEqual(box.playback_volume, 40)
            box.reconnect()
            self.assertEqual(box.device.playback_volume, 40)
            box.set_volume(0)
            voice.handle_volume_command(box, '/volume down')
            self.assertEqual(box.playback_volume, 0)
            box.set_volume(100)
            voice.handle_volume_command(box, '/volume up')
            self.assertEqual(box.playback_volume, 100)

    def test_pcm_volume_preserves_signed_samples_and_length(self):
        pcm = struct.pack('<5h', -32768, -1000, 0, 1000, 32767)
        self.assertEqual(scale_playback(pcm, 100), pcm)
        self.assertEqual(scale_playback(pcm, 0), bytes(len(pcm)))
        self.assertEqual(struct.unpack('<5h', scale_playback(pcm, 50)),
                         (-16384, -500, 0, 500, 16383))

    def test_console_microphone_off_blocks_capture_until_enabled(self):
        commands = Mock()
        commands.get_nowait.side_effect = ['/mic off', queue.Empty, '/quit']
        commands.get.side_effect = [queue.Empty, '/mic status', '/mic on']
        box = Mock(status='BOX1 OK', synchronized=True)
        with patch.object(sys, 'argv', ['voice_agent.py', '--port', '/dev/ttyACM0', '--no-wake-word']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), \
             patch.object(voice, 'create_recognizer', return_value=Mock(language='auto')), \
             patch.object(voice, 'PiRPC') as pi, \
             patch.object(voice, 'warmup_resident'), \
             patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', return_value='') as listen, \
             patch('sys.stdout', io.StringIO()) as out:
            voice.main()
        self.assertEqual(commands.get.call_count, 3)
        listen.assert_called_once()
        box.capture.assert_not_called()
        pi.return_value.ask.assert_not_called()
        self.assertIn('Microphone: OFF', out.getvalue())
        self.assertIn('Microphone: ON', out.getvalue())

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
