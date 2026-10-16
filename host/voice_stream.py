"""Bounded SSE, sentence framing and persistent HTTP connections for voice replies."""
import http.client
import json
import ssl
import socket
import time
from urllib.parse import urlsplit


class PersistentHTTP:
    """One caller owns this connection; never redirects or retries a POST."""
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.connection = None
        self.origin = None

    def close(self):
        if self.connection:
            self.connection.close()
        self.connection = None
        self.origin = None

    def cancel(self):
        # Shutdown wakes a reader without transferring connection ownership.
        connection = self.connection
        sock = getattr(connection, 'sock', None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def post(self, url, payload, headers):
        parsed = urlsplit(url)
        origin = (parsed.scheme, parsed.hostname, parsed.port)
        if origin != self.origin:
            self.close()
            cls = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
            self.connection = cls(parsed.hostname, parsed.port, timeout=self.timeout,
                                  **({'context': ssl.create_default_context()} if parsed.scheme == 'https' else {}))
            self.origin = origin
        try:
            self.connection.request('POST', parsed.path + ('?' + parsed.query if parsed.query else ''),
                                    body=json.dumps(payload).encode('utf-8'),
                                    headers={**headers, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
            response = self.connection.getresponse()
            if response.status != 200:
                status = response.status
                self.close()
                raise RuntimeError(f'Reply HTTP {status}; check provider/Gateway configuration')
            if not response.getheader('Content-Type', '').lower().startswith('text/event-stream'):
                self.close()
                raise RuntimeError('Reply endpoint did not return an SSE stream')
            return response
        except (OSError, http.client.HTTPException):
            self.close()
            raise RuntimeError('Reply connection failed; check network and retry the request') from None


def sse_events(response, timeout=90):
    started = time.monotonic()
    parts = []
    total = 0
    size = 0
    while True:
        if time.monotonic()-started > timeout:
            raise RuntimeError('Reply stream exceeded total time limit')
        line = response.readline(32770)
        if not line:
            if parts:
                raise RuntimeError('Truncated SSE event')
            return
        total += len(line)
        if total > 512 * 1024 or len(line) > 32768:
            raise RuntimeError('Reply stream exceeded size limit')
        if not line.endswith(b'\n'):
            raise RuntimeError('Truncated SSE line')
        line = line.rstrip(b'\r\n')
        if not line:
            if parts:
                yield b'\n'.join(parts).decode('utf-8')
                parts.clear()
                size = 0
        elif line.startswith(b'data:'):
            part = line[5:].removeprefix(b' ')
            size += len(part) + 1
            if size > 32768:
                raise RuntimeError('Reply event exceeded size limit')
            parts.append(part)


class Sentences:
    def __init__(self):
        self.pending = ''
        self.first = True

    def feed(self, delta):
        for char in delta:
            if self.pending.endswith(('.', '!', '?')) and char.isspace():
                yield from self.finish()
            self.pending += char
            if (self.first and char == '，' and len(self.pending) >= 24) or char in '。！？；\n' or (len(self.pending) >= 80 and char.isspace()) or len(self.pending) >= 160:
                yield from self.finish()

    def finish(self):
        text = self.pending.strip()
        self.pending = ''
        if text:
            self.first = False
            yield text
