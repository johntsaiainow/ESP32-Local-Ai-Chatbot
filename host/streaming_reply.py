"""Receive text, synthesize sentences and play them with bounded overlap."""
from pathlib import Path
import queue
import threading
import time
from offline_speech import synthesize_resident
from voice_stream import Sentences


def stream_reply(box, backend, text, temp, agent_name, language_for, pages_for):
    sentences, audio = queue.Queue(maxsize=8), queue.Queue(maxsize=2)
    cancel = threading.Event()
    errors = []
    started = time.monotonic()
    result = []

    def put(target, item):
        while not cancel.is_set():
            try:
                target.put(item, timeout=0.1)
                return
            except queue.Full:
                continue
        raise RuntimeError('Reply cancelled')

    def generate():
        splitter = Sentences()
        first_delta = first_sentence = True
        try:
            def delta(part):
                nonlocal first_delta, first_sentence
                if part and first_delta:
                    first_delta = False
                    print(f'LATENCY stage=reply_first_delta elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
                for sentence in splitter.feed(part):
                    if first_sentence:
                        first_sentence = False
                        print(f'LATENCY stage=reply_first_sentence elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
                    put(sentences, sentence)
            result.append(backend.ask(text, on_delta=delta))
            for sentence in splitter.finish():
                if first_sentence:
                    first_sentence = False
                    print(f'LATENCY stage=reply_first_sentence elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
                put(sentences, sentence)
            put(sentences, None)
        except BaseException as exc:
            errors.append(exc)
            cancel.set()

    def synthesize():
        try:
            index = 0
            while not cancel.is_set():
                try:
                    sentence = sentences.get(timeout=0.1)
                except queue.Empty:
                    continue
                if sentence is None:
                    put(audio, None)
                    return
                language = language_for(sentence)
                path = Path(temp) / f'stream-{index % 4}.wav'
                stamp = time.monotonic()
                synthesize_resident(sentence, path, language)
                print(f'LATENCY stage=tts sentence={index} elapsed_ms={(time.monotonic()-stamp)*1000:.0f}', flush=True)
                put(audio, (sentence, language, path))
                index += 1
        except BaseException as exc:
            errors.append(exc)
            cancel.set()

    workers = [threading.Thread(target=generate, daemon=True), threading.Thread(target=synthesize, daemon=True)]
    for worker in workers:
        worker.start()
    first = True
    try:
        while True:
            if errors:
                raise errors[0]
            try:
                item = audio.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                break
            sentence, language, path = item
            box.expression('speaking')
            # Commands and playback have a single owner; workers never touch the device.
            pages = list(pages_for(sentence, language))
            box.display(agent_name + '\n' + pages[0], language)
            def progress(message):
                nonlocal first
                # STREAM command acknowledgement is an upload boundary, not first DAC audio.
                if first:
                    print(f'LATENCY stage=playback_upload_start elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
                    first = False
                print(message, flush=True)
            box.play(path, progress=progress)
        if result:
            print(f'\n{agent_name}: {result[0]}\n', flush=True)
        print(f'LATENCY stage=turn elapsed_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
        return result[0] if result else ''
    finally:
        cancel.set()
        if workers[0].is_alive():
            stop = getattr(backend, 'cancel', None)
            if callable(stop):
                stop()
        # Read timeout bounds a stalled network producer; join before temporary files
        # or the next conversation turn can reuse resources.
        for worker in workers:
            while worker.is_alive():
                worker.join(timeout=0.1)
