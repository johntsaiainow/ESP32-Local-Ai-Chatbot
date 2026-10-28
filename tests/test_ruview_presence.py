"""Presence arrival behavior without a broker or sensor hardware."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from ruview_presence import PresenceTrigger, RuViewPresence
from voice_agent import WakeWordGate


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.trigger = PresenceTrigger(clock=lambda: self.now)

    def test_arrival_opens_one_request_window(self):
        gate = WakeWordGate(clock=lambda: self.now)
        self.trigger.update(True)
        if self.trigger.consume():
            gate.arm_presence()
        self.assertEqual(gate.accept('現在幾點'), '現在幾點')
        self.trigger.update(True)
        self.assertFalse(self.trigger.consume())
        self.assertIsNone(gate.accept('背景說話'))

    def test_absence_hysteresis_and_reentry(self):
        self.trigger.update(True)
        self.trigger.consume()
        self.trigger.update(False)
        self.now += 2
        self.trigger.update(True)
        self.assertFalse(self.trigger.consume())
        self.trigger.update(False)
        self.now += 5
        self.trigger.update(True)
        self.assertTrue(self.trigger.consume())

    def test_retained_expired_and_disconnected_events_do_not_wake(self):
        self.trigger.update(True, retained=True)
        self.assertFalse(self.trigger.consume())
        self.trigger.update(True)
        self.now += 11
        self.assertFalse(self.trigger.consume())
        self.trigger.disconnect()
        self.trigger.update(True)
        self.assertFalse(self.trigger.consume())

    def test_absence_cancels_pending_and_does_not_extend_debounce(self):
        self.trigger.update(True)
        self.trigger.update(False)
        self.assertFalse(self.trigger.consume())
        self.now += 4
        self.trigger.update(False)
        self.now += 1
        self.trigger.update(True)
        self.assertTrue(self.trigger.consume())

    def test_mqtt_filters_topic_payload_and_retention(self):
        adapter = RuViewPresence.__new__(RuViewPresence)
        adapter.trigger = self.trigger
        adapter.topic = 'room/presence'
        adapter.on_payload, adapter.off_payload = b'ON', b'OFF'
        for topic, payload, retained in [('other', b'ON', False),
                                         ('room/presence', b'unknown', False),
                                         ('room/presence', b'ON', True)]:
            adapter._message(None, None, SimpleNamespace(topic=topic, payload=payload, retain=retained))
            self.assertFalse(adapter.consume())
        adapter._message(None, None, SimpleNamespace(topic=adapter.topic, payload=b'ON', retain=False))
        self.assertTrue(adapter.consume())

    def test_presence_does_not_extend_an_existing_window(self):
        gate = WakeWordGate(clock=lambda: self.now)
        gate.arm_followup()
        deadline = gate.deadline
        self.now += 2
        gate.arm_presence()
        self.assertEqual(gate.deadline, deadline)
        self.now = deadline
        self.assertIsNone(gate.accept('too late'))
