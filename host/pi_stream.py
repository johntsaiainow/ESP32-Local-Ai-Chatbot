"""Read Pi's installed JSONL CLI protocol without waiting for process exit."""
import json
import re
import select
import subprocess
import tempfile
import time


def stream_pi(argv, on_delta, timeout=180, cancel=None):
    started = time.monotonic()
    pieces = []
    complete = False
    pending = b''
    first_event = first_text = agent_started = False
    tools = {}
    with tempfile.TemporaryFile() as diagnostics:
        process = subprocess.Popen([*argv[:-1], '--mode', 'json', argv[-1]], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=diagnostics)
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise RuntimeError('Pi reply cancelled')
                if time.monotonic()-started >= timeout:
                    raise RuntimeError('Pi reply timed out')
                ready, _, _ = select.select([process.stdout], [], [], 0.1)
                if not ready:
                    continue
                chunk = process.stdout.read1(4096)
                if not chunk:
                    break
                pending += chunk
                if len(pending) > 1024*1024:
                    raise RuntimeError('Pi event exceeded size limit')
                while b'\n' in pending:
                    line, _, pending = pending.partition(b'\n')
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    kind = event.get('type')
                    elapsed = (time.monotonic()-started)*1000
                    if not first_event:
                        first_event = True
                        print(f'LATENCY stage=pi_first_event elapsed_ms={elapsed:.0f}', flush=True)
                    if kind == 'agent_start' and not agent_started:
                        agent_started = True
                        print(f'LATENCY stage=pi_agent_start elapsed_ms={elapsed:.0f}', flush=True)
                    if kind == 'tool_execution_start':
                        name = re.sub(r'[^A-Za-z0-9_.-]', '_', str(event.get('toolName', 'unknown')))[:80]
                        tools[event.get('toolCallId')] = (name, time.monotonic())
                        print(f'LATENCY stage=pi_tool_start tool={name} elapsed_ms={elapsed:.0f}', flush=True)
                    elif kind == 'tool_execution_end':
                        name, tool_started = tools.pop(event.get('toolCallId'), ('unknown', time.monotonic()))
                        duration = (time.monotonic()-tool_started)*1000
                        print(f'LATENCY stage=pi_tool_end tool={name} duration_ms={duration:.0f} elapsed_ms={elapsed:.0f} failed={int(bool(event.get("isError")))}', flush=True)
                    if kind == 'message_update':
                        delta = event.get('assistantMessageEvent', {})
                        if delta.get('type') == 'text_delta':
                            text = delta.get('delta', '')
                            if not isinstance(text, str):
                                raise RuntimeError('Invalid Pi text delta')
                            if text and not first_text:
                                first_text = True
                                print(f'LATENCY stage=pi_first_text elapsed_ms={elapsed:.0f}', flush=True)
                            pieces.append(text)
                            if sum(map(len, pieces)) > 16384:
                                raise RuntimeError('Pi voice reply too long')
                            on_delta(text)
                    elif kind == 'message_end':
                        message = event.get('message', {})
                        if message.get('role') == 'assistant' and message.get('stopReason') in ('error', 'aborted'):
                            raise RuntimeError('Pi assistant response failed or aborted')
                    elif kind == 'agent_settled':
                        complete = not event.get('aborted', False)
            code = process.wait(timeout=max(0.1, timeout-(time.monotonic()-started)))
            if code or pending.strip() or not complete or not ''.join(pieces).strip():
                raise RuntimeError('Pi did not finish a complete JSON reply; check Pi CLI/version and logs')
            print(f'LATENCY stage=pi_complete elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
            return ''.join(pieces).strip()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
