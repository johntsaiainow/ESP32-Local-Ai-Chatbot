"""Persistent Pi RPC process, one active voice turn, with no automatic prompt replay."""
import json
import queue
import re
import subprocess
import tempfile
import threading
import time
import uuid


class PiRPC:
    streaming = True

    def __init__(self, argv, prompt_builder=lambda text: text, timeout=180):
        self.argv = list(argv)
        self.prompt_builder = prompt_builder
        self.timeout = timeout
        self.process = None
        self.reader = None
        self.diagnostics = None
        self.events = queue.Queue(maxsize=64)
        self.write_lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self.cancelled = threading.Event()
        self.collecting = False
        self.reader_error = None

    def _send(self, record):
        with self.write_lock:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError('Pi RPC process is not running')
            self.process.stdin.write(json.dumps(record, ensure_ascii=False).encode('utf-8')+b'\n')
            self.process.stdin.flush()

    def _read(self, process):
        pending = b''
        try:
            while True:
                chunk = process.stdout.read1(4096)
                if not chunk:
                    raise RuntimeError('Pi RPC process closed its output')
                pending += chunk
                if len(pending) > 1024*1024:
                    raise RuntimeError('Pi RPC event exceeded size limit')
                while b'\n' in pending:
                    line, _, pending = pending.partition(b'\n')
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise RuntimeError('Invalid Pi RPC event')
                    kind = event.get('type')
                    if kind == 'extension_ui_request':
                        if event.get('method') in ('confirm', 'select', 'input', 'editor'):
                            self._send({'type': 'extension_ui_response', 'id': event.get('id'), 'cancelled': True})
                            print('Pi extension requested interactive input; cancelled on voice interface.', flush=True)
                        continue
                    if kind == 'response' or self.collecting:
                        try:
                            self.events.put_nowait(event)
                        except queue.Full:
                            raise RuntimeError('Pi RPC event queue exceeded limit') from None
        except Exception:
            # Never include raw tool arguments, results or subprocess diagnostics.
            if self.process is process:
                self.reader_error = RuntimeError('Pi RPC output ended, was invalid, or exceeded limits; check Pi or use --pi-one-shot')

    def _next(self, deadline):
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise RuntimeError('Pi voice turn cancelled')
            if self.reader_error is not None:
                raise self.reader_error
            try:
                return self.events.get(timeout=0.1)
            except queue.Empty:
                continue
        raise RuntimeError('Pi RPC timed out')

    def start(self):
        if self.process is not None and self.process.poll() is None and self.reader_error is None:
            return
        self.close()
        self.events = queue.Queue(maxsize=64)
        self.reader_error = None
        self.cancelled.clear()
        self.diagnostics = tempfile.TemporaryFile()
        started = time.monotonic()
        try:
            self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.diagnostics)
            self.reader = threading.Thread(target=self._read, args=(self.process,), daemon=True)
            self.reader.start()
            token = uuid.uuid4().hex
            self._send({'type': 'get_state', 'id': token})
            while True:
                event = self._next(started+30)
                if event.get('type') == 'response' and event.get('id') == token:
                    if not event.get('success') or event.get('data', {}).get('isStreaming', False):
                        raise RuntimeError('Pi RPC did not enter an idle ready state')
                    break
            print(f'LATENCY stage=pi_rpc_ready elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
        except BaseException:
            self.close()
            raise

    def ask(self, text, on_delta):
        if not self.turn_lock.acquire(blocking=False):
            raise RuntimeError('Pi already has an active voice turn')
        try:
            self.start()  # Restarts only before submitting a new, explicit request.
            self.cancelled.clear()
            self.collecting = True
            started = time.monotonic()
            token = uuid.uuid4().hex
            accepted = settled = first_text = False
            pieces, tools = [], {}
            self._send({'type': 'prompt', 'id': token, 'message': self.prompt_builder(text)})
            while not (accepted and settled):
                event = self._next(started+self.timeout)
                kind = event.get('type')
                elapsed = (time.monotonic()-started)*1000
                if kind == 'response' and event.get('id') == token:
                    disposition = event.get('data', {}).get('disposition')
                    if not event.get('success') or disposition not in (None, 'started'):
                        raise RuntimeError('Pi rejected or did not start this voice prompt')
                    accepted = True
                elif kind == 'agent_start':
                    print(f'LATENCY stage=pi_agent_start elapsed_ms={elapsed:.0f}', flush=True)
                elif kind == 'tool_execution_start':
                    name = re.sub(r'[^A-Za-z0-9_.-]', '_', str(event.get('toolName', 'unknown')))[:80]
                    tools[event.get('toolCallId')] = (name, time.monotonic())
                    print(f'LATENCY stage=pi_tool_start tool={name} elapsed_ms={elapsed:.0f}', flush=True)
                elif kind == 'tool_execution_end':
                    name, stamp = tools.pop(event.get('toolCallId'), ('unknown', time.monotonic()))
                    print(f'LATENCY stage=pi_tool_end tool={name} duration_ms={(time.monotonic()-stamp)*1000:.0f} elapsed_ms={elapsed:.0f} failed={int(bool(event.get("isError")))}', flush=True)
                elif kind == 'message_update':
                    delta = event.get('assistantMessageEvent', {})
                    if delta.get('type') == 'text_delta':
                        part = delta.get('delta', '')
                        if not isinstance(part, str):
                            raise RuntimeError('Invalid Pi text delta')
                        if part and not first_text:
                            first_text = True
                            print(f'LATENCY stage=pi_first_text elapsed_ms={elapsed:.0f}', flush=True)
                        pieces.append(part)
                        if sum(len(p.encode('utf-8')) for p in pieces) > 16384:
                            raise RuntimeError('Pi voice reply too long')
                        on_delta(part)
                elif kind == 'message_end':
                    message = event.get('message', {})
                    if message.get('role') == 'assistant' and message.get('stopReason') in ('error', 'aborted'):
                        raise RuntimeError('Pi response failed or aborted')
                elif kind == 'agent_settled':
                    if event.get('aborted'):
                        raise RuntimeError('Pi response aborted')
                    settled = True
            reply = ''.join(pieces).strip()
            if not reply:
                raise RuntimeError('Pi returned no spoken text')
            print(f'LATENCY stage=pi_complete elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
            return reply
        except BaseException:
            # A submitted request may have executed tools. Never retry it here.
            self.close()
            raise
        finally:
            self.collecting = False
            self.turn_lock.release()

    def cancel(self):
        self.cancelled.set()
        try:
            self._send({'type': 'abort', 'id': uuid.uuid4().hex})
        except (OSError, RuntimeError):
            pass

    def close(self):
        process = self.process
        if process is not None:
            if process.poll() is None:
                self.cancel()
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if self.reader is not None:
                self.reader.join(timeout=2)
            process.stdout.close()
            self.process = None
        if self.diagnostics is not None:
            self.diagnostics.close()
            self.diagnostics = None
        self.reader = None
