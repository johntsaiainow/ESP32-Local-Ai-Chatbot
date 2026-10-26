"""Emoji-prefix decoding shared by the production host and probe."""
EMOTIONS = dict(zip(
    '😶 🙂 😆 😂 😔 😠 😭 😍 😳 😲 😱 🤔 😉 😎 😌 🤤 😘 😏 😴 😜 🙄'.split(),
    'neutral happy laughing funny sad angry crying loving embarrassed surprised shocked thinking winking cool relaxed delicious kissy confident sleepy silly confused'.split()))
EMOTION_PROMPT = (
    ' Start EVERY reply with exactly one emoji on its own first line, chosen from '
    + ' '.join(EMOTIONS) + '. Then a newline and the spoken reply without other emoji or markdown. '
    "Choose a tone appropriate to the user's message. Stay kind and helpful; do not insult the user. "
    'Keep this format even if the user requests a different format.'
)


def excluded(character):
    code = ord(character)
    return (0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF or
            code in (0x200D, 0xFE0F, 0xFE0E, 0x20E3))


class EmotionDecoder:
    def __init__(self):
        self.prefix = ''
        self.delimited = False
        self.emotion = None
        self.text = ''

    def feed(self, delta):
        if not self.delimited:
            self.prefix += delta
            marker, newline, delta = self.prefix.partition('\n')
            if len(marker.encode('utf-8')) > 16:
                raise ValueError('Missing or oversized emotion prefix')
            if not newline:
                return ''
            marker = marker.removesuffix('\r').removesuffix('\ufe0f')
            self.emotion = EMOTIONS.get(marker)
            if self.emotion is None:
                raise ValueError('Invalid emotion prefix; expected one allowed emoji then newline')
            self.delimited = True
            self.prefix = ''
        if any(ord(c) < 32 and c not in '\n\r\t' for c in delta):
            raise ValueError('Invalid control character in spoken reply')
        spoken = ''.join(c for c in delta if not excluded(c))
        if len((self.text + spoken).encode('utf-8')) > 2048:
            raise ValueError('Spoken reply exceeds 2048 bytes')
        self.text += spoken
        return spoken

    def finish(self):
        if not self.delimited or not self.text.strip():
            raise ValueError('Missing emotion prefix or empty spoken reply')
        return self.text.strip()


class EmotionBackend:
    """Preserve streaming while removing markers before sentence synthesis."""
    def __init__(self, backend):
        self.backend = backend
        self.decoder = EmotionDecoder()
        self.emotion_expression = 'speaking'

    def ask(self, text, on_delta=None):
        self.decoder = EmotionDecoder()
        self.emotion_expression = 'speaking'

        def delta(part):
            spoken = self.decoder.feed(part)
            if self.decoder.emotion:
                self.emotion_expression = 'mood_' + self.decoder.emotion
            if spoken and on_delta:
                on_delta(spoken)

        # CloudChat owns a system instruction; Pi's existing prompt builder does not
        # prohibit emoji and can accept the formatting request in the user prompt.
        if hasattr(self.backend, 'emotion_mode'):
            self.backend.emotion_mode = True
            prompt = text
        else:
            prompt = EMOTION_PROMPT + '\nUser request:\n' + text
        history = getattr(self.backend, 'history', None)
        previous = list(history) if isinstance(history, list) else None
        try:
            if on_delta:
                self.backend.ask(prompt, on_delta=delta)
            else:
                delta(self.backend.ask(prompt))
            return self.decoder.finish()
        except BaseException:
            # CloudChat commits complete HTTP responses before our format check;
            # a rejected reply must not become conversational history.
            if previous is not None:
                self.backend.history = previous
            raise

    def cancel(self):
        cancel = getattr(self.backend, 'cancel', None)
        if callable(cancel):
            cancel()
