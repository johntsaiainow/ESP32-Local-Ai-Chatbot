"""Detect periodic zero padding that indicates broken PCM framing."""
from array import array
import sys


def has_periodic_zero_padding(pcm):
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    if len(samples) < 1600:
        return False
    phases = [0] * 16
    for index, value in enumerate(samples):
        if value:
            phases[index % 16] += 1
    nonzero = sum(phases)
    return (nonzero >= 100 and nonzero <= len(samples) * 0.2 and
            sum(sorted(phases)[-2:]) >= nonzero * 0.99)


def require_valid_framing(pcm):
    if has_periodic_zero_padding(pcm):
        raise RuntimeError(
            'Microphone PCM has periodic zero padding (only two of sixteen sample '
            'positions carry audio). Upload the slot32-v3 codec/I2S firmware and '
            'record again; changing volume or the recognition model cannot repair it.')
