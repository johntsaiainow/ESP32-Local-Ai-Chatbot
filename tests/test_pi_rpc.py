"""Persistent RPC lifecycle using a local synthetic Pi; no inference or network."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1]/'host'))
from pi_rpc import PiRPC

SERVER = r'''
import json, os, sys
count = 0
active = False
def send(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)
for line in sys.stdin.buffer:
    command = json.loads(line)
    kind, token = command['type'], command.get('id')
    if kind == 'get_state':
        send({'type':'response','id':token,'command':kind,'success':True,'data':{'isStreaming':False}})
    elif kind == 'prompt':
        message = command['message']
        with open(sys.argv[1], 'a') as log:
            log.write(message+'\n')
        if message == 'crash':
            os._exit(2)
        if message == 'reject':
            send({'type':'response','id':token,'success':False,'error':'private-diagnostic'})
            continue
        if message == 'handled':
            send({'type':'response','id':token,'success':True,'data':{'disposition':'handled'}})
            continue
        count += 1
        send({'type':'response','id':token,'success':True,'data':{'disposition':'started'}})
        send({'type':'agent_start'})
        send({'type':'message_update','assistantMessageEvent':{'type':'thinking_delta','delta':'private-thought'}})
        send({'type':'message_update','assistantMessageEvent':{'type':'text_delta','delta':f'Reply {count} 你好。'}})
        if message == 'hang':
            active=True
            continue
        if message == 'dialog':
            send({'type':'extension_ui_request','method':'confirm','id':'dialog'})
            active=True
            continue
        send({'type':'agent_end','willRetry':False})
        send({'type':'agent_settled','aborted':False})
    elif kind == 'extension_ui_response':
        if command.get('cancelled') is not True:
            os._exit(3)
        send({'type':'agent_settled','aborted':False})
    elif kind == 'abort':
        send({'type':'response','id':token,'success':True})
        if active:
            send({'type':'agent_settled','aborted':True})
            active=False
'''

class PiRPCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        script = Path(self.temp.name)/'pi.py'
        script.write_text(SERVER)
        self.log = Path(self.temp.name)/'prompts.log'
        self.pi = PiRPC([sys.executable, str(script), str(self.log)], timeout=3)
        self.addCleanup(self.pi.close)

    def test_two_turns_share_process_and_reader_drains_while_idle(self):
        self.pi.start()
        pid = self.pi.process.pid
        first, second = [], []
        self.assertEqual(self.pi.ask('first', first.append), 'Reply 1 你好。')
        self.assertEqual(self.pi.ask('second', second.append), 'Reply 2 你好。')
        self.assertEqual(self.pi.process.pid, pid)
        self.assertEqual(self.log.read_text().splitlines(), ['first','second'])
        self.assertNotIn('private-thought', ''.join(first+second))

    def test_crash_does_not_replay_prompt_and_next_explicit_turn_can_restart(self):
        with self.assertRaises(RuntimeError):
            self.pi.ask('crash', lambda _: None)
        self.assertIsNone(self.pi.process)
        self.assertEqual(self.log.read_text().splitlines(), ['crash'])
        self.assertEqual(self.pi.ask('new', lambda _: None), 'Reply 1 你好。')
        self.assertEqual(self.log.read_text().splitlines(), ['crash','new'])

    def test_rejected_and_handled_requests_do_not_wait_for_model(self):
        for message in ('reject','handled'):
            with self.subTest(message=message), self.assertRaises(RuntimeError) as caught:
                self.pi.ask(message, lambda _: None)
            self.assertNotIn('private-diagnostic', str(caught.exception))

    def test_cancel_stops_active_turn_and_joins_process(self):
        seen = threading.Event()
        errors=[]
        def ask():
            try:
                self.pi.ask('hang', lambda _: seen.set())
            except RuntimeError as error:
                errors.append(error)
        worker=threading.Thread(target=ask)
        worker.start()
        self.assertTrue(seen.wait(3))
        self.pi.cancel()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors),1)
        self.assertIsNone(self.pi.process)

    def test_dialog_is_cancelled_never_automatically_approved(self):
        self.assertEqual(self.pi.ask('dialog', lambda _: None), 'Reply 1 你好。')

    def test_timeout_closes_process_without_replaying(self):
        self.pi.timeout = 0.15
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            self.pi.ask('hang', lambda _: None)
        self.assertIsNone(self.pi.process)
        self.assertEqual(self.log.read_text().splitlines(), ['hang'])
