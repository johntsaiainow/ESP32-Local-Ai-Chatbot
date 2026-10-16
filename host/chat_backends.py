"""Optional cloud text replies; device audio and speech processing stay on host."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

INSTRUCTIONS = (
    'You are Osiris, a conversational voice assistant. Reply concisely in under 50 words. '
    'Use Traditional Chinese for Chinese requests; otherwise use English. '
    'Avoid code blocks unless requested. You have no tools, live weather, web search, '
    'filesystem access, or device controls. Never claim to perform those actions or invent live facts. '
    'Local music playback is handled separately by the host.'
)


class CloudChat:
    """One bounded, in-memory conversation using official provider REST endpoints."""
    def __init__(self, provider, model=None, timeout=90):
        if provider not in ('openai', 'gemini'):
            raise ValueError('Cloud provider must be openai or gemini')
        self.provider = provider
        variable = 'OPENAI_API_KEY' if provider == 'openai' else 'GEMINI_API_KEY'
        self.key = os.environ.get(variable, '').strip()
        if not self.key:
            raise ValueError(f'Set {variable} on the host to use {provider}')
        model_variable = f'BOX3_{provider.upper()}_MODEL'
        self.model = (model or os.environ.get(model_variable, '')).strip()
        if not self.model:
            raise ValueError(f'Choose a model with --model or {model_variable}')
        self.timeout = timeout
        self.history = []

    def ask(self, text):
        messages = self.history + [{'role': 'user', 'content': text}]
        if self.provider == 'openai':
            url = 'https://api.openai.com/v1/responses'
            payload = {'model': self.model, 'instructions': INSTRUCTIONS,
                       'input': messages, 'store': False}
            headers = {'Authorization': 'Bearer ' + self.key}
        else:
            url = ('https://generativelanguage.googleapis.com/v1beta/models/' +
                   quote(self.model, safe='') + ':generateContent')
            payload = {'systemInstruction': {'parts': [{'text': INSTRUCTIONS}]},
                       'contents': [{'role': 'model' if item['role'] == 'assistant' else 'user',
                                     'parts': [{'text': item['content']}]} for item in messages]}
            headers = {'x-goog-api-key': self.key}
        request = Request(url, data=json.dumps(payload).encode('utf-8'),
                          headers={**headers, 'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            # Provider error bodies may contain request data; never print them or keys.
            raise RuntimeError(f'{self.provider} HTTP {exc.code}; check API key, model access, quota, and rate limits') from None
        except (URLError, TimeoutError):
            raise RuntimeError(f'{self.provider} connection failed or timed out; check internet access') from None
        except (ValueError, UnicodeError):
            raise RuntimeError(f'{self.provider} returned invalid JSON') from None
        if not isinstance(data, dict):
            raise RuntimeError(f'{self.provider} returned an invalid response object')
        if self.provider == 'openai':
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
