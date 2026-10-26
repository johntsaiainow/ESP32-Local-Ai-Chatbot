"""Optional cloud text replies; device audio and speech processing stay on host."""
import json
import os
import time
from voice_stream import PersistentHTTP, sse_events
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

INSTRUCTIONS = (
    'You are Osiris, a conversational voice assistant. Reply concisely in under 50 words. '
    'Use Traditional Chinese for Chinese requests; otherwise use English. '
    'Avoid code blocks unless requested. You have no tools, live weather, web search, '
    'filesystem access, or device controls. Never claim to perform those actions or invent live facts. '
    'Local music playback is handled separately by the host.'
)


OPENCLAW_INSTRUCTIONS = (
    "Reply in the user's language; use Traditional Chinese for Chinese. "
    "Keep spoken replies under 50 words, without markdown or emoji. "
    "Only claim actions confirmed by your tools."
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a Gateway operator token to a redirected URL.


def openclaw_endpoint(base):
    try:
        parsed = urlsplit(base)
        valid = (len(base) <= 256 and parsed.scheme in ('http', 'https') and parsed.hostname and
                 all(c.isascii() and (c.isalnum() or c in '.-') for c in parsed.hostname) and
                 parsed.username is None and parsed.password is None and not parsed.query and
                 not parsed.fragment and parsed.path.rstrip('/') in ('', '/v1') and
                 (parsed.port is None or 1 <= parsed.port <= 65535) and
                 not any(ord(c) <= 32 or ord(c) >= 127 or c in '<>"&' for c in base))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('OPENCLAW_GATEWAY_URL must be an HTTP(S) origin, optionally ending in /v1')
    return base.rstrip('/') + ('/chat/completions' if parsed.path.rstrip('/') == '/v1' else '/v1/chat/completions')


class CloudChat:
    """One bounded, in-memory conversation using official provider REST endpoints."""
    def __init__(self, provider, model=None, timeout=90):
        if provider not in ('openai', 'gemini', 'openclaw'):
            raise ValueError('Cloud provider must be openai, gemini, or openclaw')
        self.provider = provider
        self.emotion_mode = False
        variable = {'openai': 'OPENAI_API_KEY', 'gemini': 'GEMINI_API_KEY',
                    'openclaw': 'OPENCLAW_GATEWAY_TOKEN'}[provider]
        self.key = os.environ.get(variable, '').strip()
        if not self.key:
            raise ValueError(f'Set {variable} on the host to use {provider}')
        model_variable = f'BOX3_{provider.upper()}_MODEL'
        self.model = (model or os.environ.get(model_variable, 'openclaw/default' if provider == 'openclaw' else '')).strip()
        if not self.model:
            raise ValueError(f'Choose a model with --model or {model_variable}')
        if provider == 'openclaw':
            self.url = openclaw_endpoint(os.environ.get('OPENCLAW_GATEWAY_URL', 'http://127.0.0.1:18789').strip())
            if len(self.key) > 256 or any(ord(c) <= 32 or ord(c) >= 127 for c in self.key):
                raise ValueError('OPENCLAW_GATEWAY_TOKEN must contain printable characters without spaces')
            if not self.model.startswith('openclaw/') or not 1 <= len(self.model[9:]) <= 64 or any(
                    not (c.isascii() and (c.isalnum() or c in '._-')) for c in self.model[9:]):
                raise ValueError('OpenClaw --model must be openclaw/<agentId> (default: openclaw/default)')
        self.timeout = timeout
        self.history = []
        self.http = PersistentHTTP(min(timeout, 30))
        self.streaming = True

    def close(self):
        self.http.close()

    def cancel(self):
        self.http.cancel()

    def instructions(self, openclaw=False):
        text = OPENCLAW_INSTRUCTIONS if openclaw else INSTRUCTIONS
        if self.emotion_mode:
            from emotion_runtime import EMOTION_PROMPT
            text = text.replace('without markdown or emoji', 'without markdown') + EMOTION_PROMPT
        return text

    def ask(self, text, on_delta=None):
        if on_delta is not None:
            return self._ask_stream(text, on_delta)
        messages = self.history + [{'role': 'user', 'content': text}]
        if self.provider == 'openclaw':
            url = self.url
            payload = {'model': self.model, 'stream': False,
                       'messages': [{'role': 'system', 'content': self.instructions(True)}] + messages}
            headers = {'Authorization': 'Bearer ' + self.key}
        elif self.provider == 'openai':
            url = 'https://api.openai.com/v1/responses'
            payload = {'model': self.model, 'instructions': self.instructions(),
                       'input': messages, 'store': False}
            headers = {'Authorization': 'Bearer ' + self.key}
        else:
            url = ('https://generativelanguage.googleapis.com/v1beta/models/' +
                   quote(self.model, safe='') + ':generateContent')
            payload = {'systemInstruction': {'parts': [{'text': self.instructions()}]},
                       'contents': [{'role': 'model' if item['role'] == 'assistant' else 'user',
                                     'parts': [{'text': item['content']}]} for item in messages]}
            headers = {'x-goog-api-key': self.key}
        request = Request(url, data=json.dumps(payload).encode('utf-8'),
                          headers={**headers, 'Content-Type': 'application/json'}, method='POST')
        try:
            send = build_opener(NoRedirect()).open if self.provider == 'openclaw' else urlopen
            with send(request, timeout=self.timeout) as response:
                if self.provider == 'openclaw':
                    raw = response.read(128 * 1024 + 1)
                    if len(raw) > 128 * 1024:
                        raise RuntimeError('Reply exceeded 128 KiB limit')
                    data = json.loads(raw)
                else:
                    data = json.load(response)
        except HTTPError as exc:
            # Provider error bodies may contain request data; never print them or keys.
            exc.close()
            advice = ('check Gateway URL, token, enabled endpoint and agent logs' if self.provider == 'openclaw'
                      else 'check API key, model access, quota, and rate limits')
            raise RuntimeError(f'{self.provider} HTTP {exc.code}; {advice}') from None
        except (URLError, TimeoutError):
            raise RuntimeError(f'{self.provider} connection failed or timed out; check internet access') from None
        except (ValueError, UnicodeError):
            raise RuntimeError(f'{self.provider} returned invalid JSON') from None
        if not isinstance(data, dict):
            raise RuntimeError(f'{self.provider} returned an invalid response object')
        if self.provider == 'openclaw':
            choices = data.get('choices')
            choice = choices[0] if isinstance(choices, list) and choices else {}
            if not isinstance(choice, dict) or choice.get('finish_reason') != 'stop':
                raise RuntimeError('OpenClaw reply incomplete or requires unsupported client tools')
            message = choice.get('message')
            reply = message.get('content') if isinstance(message, dict) else None
            if not isinstance(reply, str):
                raise RuntimeError('OpenClaw returned no spoken text')
        elif self.provider == 'openai':
            if data.get('status') not in (None, 'completed'):
                raise RuntimeError('openai response did not complete')
            reply = '\n'.join(part['text'] for item in data.get('output', [])
                              if item.get('type') == 'message' and item.get('role') == 'assistant'
                              for part in item.get('content', [])
                              if part.get('type') == 'output_text' and isinstance(part.get('text'), str))
        else:
            candidates = data.get('candidates', [])
            candidate = candidates[0] if candidates else {}
            if candidate.get('finishReason') not in (None, 'STOP'):
                raise RuntimeError('gemini reply was blocked or incomplete')
            reply = '\n'.join(part['text'] for part in candidate.get('content', {}).get('parts', [])
                              if isinstance(part.get('text'), str) and not part.get('thought', False))
        reply = reply.strip()
        if not reply:
            raise RuntimeError(f'{self.provider} returned no spoken text (empty or blocked response)')
        # Commit complete turns only. Failed requests never pollute the conversation.
        self.history = (messages + [{'role': 'assistant', 'content': reply}])[-24:]
        return reply

    def _ask_stream(self, text, on_delta):
        messages = self.history + [{'role': 'user', 'content': text}]
        if self.provider == 'openai':
            url = 'https://api.openai.com/v1/responses'
            payload = {'model': self.model, 'instructions': self.instructions(),
                       'input': messages, 'store': False, 'stream': True}
            headers = {'Authorization': 'Bearer ' + self.key}
        elif self.provider == 'openclaw':
            url = self.url
            payload = {'model': self.model, 'stream': True,
                       'messages': [{'role': 'system', 'content': self.instructions(True)}] + messages}
            headers = {'Authorization': 'Bearer ' + self.key}
        else:
            url = ('https://generativelanguage.googleapis.com/v1beta/models/' +
                   quote(self.model, safe='') + ':streamGenerateContent?alt=sse')
            payload = {'systemInstruction': {'parts': [{'text': self.instructions()}]},
                       'contents': [{'role': 'model' if item['role'] == 'assistant' else 'user',
                                     'parts': [{'text': item['content']}]} for item in messages]}
            headers = {'x-goog-api-key': self.key}
        reply = ''
        complete = done = False
        started = time.monotonic()
        first = None
        try:
            with self.http.post(url, payload, headers) as response:
                for raw in sse_events(response, self.timeout):
                    if raw == '[DONE]':
                        if self.provider != 'openclaw' or not complete:
                            raise RuntimeError('Unexpected end of reply stream')
                        done = True
                        continue
                    data = json.loads(raw)
                    if not isinstance(data, dict) or 'error' in data:
                        raise RuntimeError('Provider returned a streaming error')
                    was_complete = complete
                    delta = ''
                    if self.provider == 'openai':
                        kind = data.get('type', '')
                        if kind == 'response.output_text.delta':
                            delta = data.get('delta', '')
                        elif kind == 'response.completed':
                            complete = data.get('response', {}).get('status') == 'completed'
                            if not complete:
                                raise RuntimeError('Reply incomplete')
                        elif kind in ('error', 'response.failed', 'response.incomplete') or kind.startswith('response.refusal'):
                            raise RuntimeError('Reply failed, incomplete or refused')
                    elif self.provider == 'openclaw':
                        choices = data.get('choices', [])
                        choice = choices[0] if choices else {}
                        chunk = choice.get('delta', {})
                        if chunk.get('tool_calls') or chunk.get('refusal'):
                            raise RuntimeError('Unsupported client tools or refused reply')
                        delta = chunk.get('content', '') or ''
                        reason = choice.get('finish_reason')
                        if reason is not None:
                            if reason != 'stop':
                                raise RuntimeError('OpenClaw reply incomplete')
                            complete = True
                    else:
                        if data.get('promptFeedback', {}).get('blockReason'):
                            raise RuntimeError('Gemini reply blocked')
                        candidates = data.get('candidates', [])
                        candidate = candidates[0] if candidates else {}
                        delta = ''.join(part.get('text', '') for part in candidate.get('content', {}).get('parts', [])
                                        if not part.get('thought'))
                        reason = candidate.get('finishReason')
                        if reason is not None:
                            if reason != 'STOP':
                                raise RuntimeError('Gemini reply incomplete or blocked')
                            complete = True
                    if not isinstance(delta, str) or len(reply.encode('utf-8')) + len(delta.encode('utf-8')) > 16384:
                        raise RuntimeError('Reply text exceeded limit or has invalid format')
                    if delta:
                        if was_complete:
                            raise RuntimeError('Text arrived after reply completion')
                        if first is None:
                            first = time.monotonic()
                            print(f'LATENCY stage=llm_first_text elapsed_ms={(first-started)*1000:.0f}', flush=True)
                        reply += delta
                        on_delta(delta)
            if not complete or (self.provider == 'openclaw' and not done) or not reply.strip():
                raise RuntimeError('Reply stream ended before a complete text answer')
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            self.http.close()
            raise RuntimeError('Invalid or interrupted reply stream') from None
        except BaseException:
            self.http.close()
            raise
        print(f'LATENCY stage=llm elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
        reply = reply.strip()
        self.history = (messages + [{'role': 'assistant', 'content': reply}])[-24:]
        return reply
