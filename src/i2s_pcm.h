#pragma once
#include <stdint.h>

namespace osiris_pcm {
// INMP441's signed 24 bits are left aligned in a 32-bit I2S slot. Preserve
// polarity/full-scale when reducing to PCM16; do not interpret interleaved
// halves of a 32-bit sample as independent 16-bit samples.
inline int16_t fromSlot32(int32_t slot) { return static_cast<int16_t>(static_cast<uint32_t>(slot) >> 16); }
inline int32_t toSlot32(int16_t sample) { return static_cast<int32_t>(sample) * 65536; }
inline int16_t gain16(int16_t sample, unsigned gain) {
  const int64_t value = static_cast<int64_t>(sample) * gain;
  return static_cast<int16_t>(value > 32767 ? 32767 : value < -32768 ? -32768 : value);
}
} // namespace osiris_pcm
