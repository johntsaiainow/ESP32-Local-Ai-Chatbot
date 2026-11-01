import io
from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from box3 import Box3
import voice_agent as voice


class BatteryTests(unittest.TestCase):
    def test_protocol_and_unknown_presence_are_preserved(self):
        box = Box3.__new__(Box3)
        box.status = 'BOX1 OK battery=1'
        box.command = Mock(return_value=(b'', 'BOX1 OK battery_mv=3800 percent_estimate=50 presence=unknown charging=unknown'))
        result = box.battery()
        self.assertEqual(result['percent_estimate'], 50)
        self.assertEqual(result['presence'], 'unknown')
        self.assertIn('無法確定', voice.battery_reply(result))
        box.command.return_value = (b'', 'BOX1 OK battery_mv=0 percent_estimate=-1 presence=unknown charging=unknown')
        self.assertIsNone(box.battery()['percent_estimate'])
        for reply in ('BOX1 OK', 'BOX1 OK battery_mv=-2 percent_estimate=101 presence=unknown charging=unknown'):
            box.command.return_value = (b'', reply)
            with self.assertRaises(ValueError):
                box.battery()
        box.status = 'BOX1 OK battery=0'
        box.command.reset_mock()
        with self.assertRaises(ValueError):
            box.battery()
        box.command.assert_not_called()

    def test_queries_are_complete_phrases(self):
        for text in ('電池電量多少？', '电池电压', '有沒有裝電池', '/battery'):
            self.assertTrue(voice.battery_query(text), text)
        for text in ('如何更換電池', '電量是怎麼計算的', '明天會沒電嗎'):
            self.assertFalse(voice.battery_query(text), text)

    def test_spoken_battery_query_stays_local(self):
        commands = Mock()
        commands.get_nowait.side_effect = [queue.Empty, '/quit']
        box = Mock(status='BOX1 OK', synchronized=True)
        box.battery.return_value = dict(millivolts=3800, percent_estimate=50)
        with patch.object(sys, 'argv', ['voice_agent.py', '--ignore-config', '--port', '/dev/test', '--no-wake-word']), \
             patch.object(voice.queue, 'Queue', return_value=commands), \
             patch.object(voice.threading, 'Thread'), \
             patch.object(voice, 'create_recognizer'), patch.object(voice, 'PiRPC') as pi, \
             patch.object(voice, 'warmup_resident'), patch.object(voice, 'Box3Connection', return_value=box), \
             patch.object(voice, 'listen_once', return_value='電量多少'), \
             patch.object(voice, 'speak_reply') as speak, patch('sys.stdout', io.StringIO()):
            voice.main()
        box.battery.assert_called_once()
        pi.return_value.ask.assert_not_called()
        self.assertIn('3.80', speak.call_args.args[1])
        self.assertIn('無法確定', speak.call_args.args[1])
