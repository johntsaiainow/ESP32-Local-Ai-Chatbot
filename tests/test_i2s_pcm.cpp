#include "../src/i2s_pcm.h"
#include <cassert>
#include <climits>
#include <cstdio>
int main() {
  using namespace osiris_pcm;
  assert(fromSlot32(0x12345600) == 0x1234);
  assert(fromSlot32(0x7FFFFF00) == 32767);
  assert(fromSlot32(INT32_MIN) == -32768);
  assert(fromSlot32(static_cast<int32_t>(0xFFFFFF00u)) == -1);
  assert(fromSlot32(0x0000FF00) == 0);
  assert(toSlot32(-32768) == INT32_MIN);
  assert(toSlot32(32767) == 0x7FFF0000);
  assert(gain16(1234, 4) == 4936);
  assert(gain16(-1234, 4) == -4936);
  assert(gain16(10000, 4) == 32767);
  assert(gain16(-10000, 4) == -32768);
  assert(gain16(-32768, 32) == -32768);
  // Every PCM16 value must survive expansion to a wire slot and reduction.
  for (int n = -32768; n <= 32767; ++n) assert(fromSlot32(toSlot32(static_cast<int16_t>(n))) == n);
  puts("32-bit I2S / PCM16 conversion checks passed.");
}
