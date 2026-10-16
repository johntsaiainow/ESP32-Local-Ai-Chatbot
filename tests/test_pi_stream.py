"""Pi JSON framing and completion using a synthetic local CLI, never a model."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]/'host'))
from pi_stream import stream_pi

class PiStreamTests(unittest.TestCase):
    def run_cli(self, events, callback, exit_code=0):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp)/'pi.py'
            script.write_text('import sys\n' + ''.join('print('+repr(json.dumps(event))+', flush=True)\n' for event in events) + f'sys.exit({exit_code})\n')
            return stream_pi([sys.executable, str(script), 'prompt'], callback, timeout=3)

    def test_only_text_deltas_are_spoken_and_unicode_separators_stay_in_text(self):
        out = []
        events = [{'type': 'session'},
                  {'type': 'message_update', 'assistantMessageEvent': {'type': 'thinking_delta', 'delta': 'private'}},
                  {'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': 'Hello\u2028world.'}},
                  {'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'stop'}},
                  {'type': 'agent_settled', 'aborted': False}]
        self.assertEqual(self.run_cli(events, out.append), 'Hello\u2028world.')
        self.assertEqual(out, ['Hello\u2028world.'])

    def test_missing_completion_abort_or_failed_exit_is_reported(self):
        delta = {'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': 'Partial'}}
        for events, code in (([delta], 0), ([delta, {'type': 'agent_settled', 'aborted': True}], 0),
                             ([delta, {'type': 'agent_settled', 'aborted': False}], 1)):
            with self.subTest(events=events, code=code), self.assertRaises(RuntimeError):
                self.run_cli(events, lambda _: None, code)

    def test_timing_identifies_tools_without_disclosing_arguments_or_results(self):
        import io
        from unittest.mock import patch
        events = [{'type': 'agent_start'},
                  {'type': 'tool_execution_start', 'toolCallId': 'a', 'toolName': 'weather', 'args': {'secret': 'private-location'}},
                  {'type': 'tool_execution_end', 'toolCallId': 'a', 'toolName': 'weather', 'isError': False, 'result': 'private-result'},
                  {'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': 'Hello.'}},
                  {'type': 'agent_settled', 'aborted': False}]
        with patch('sys.stdout', io.StringIO()) as output:
            self.run_cli(events, lambda _: None)
        log = output.getvalue()
        for marker in ('pi_first_event', 'pi_agent_start', 'pi_tool_start tool=weather', 'pi_tool_end tool=weather', 'pi_first_text', 'pi_complete'):
            self.assertIn(marker, log)
        self.assertNotIn('private-location', log)
        self.assertNotIn('private-result', log)
