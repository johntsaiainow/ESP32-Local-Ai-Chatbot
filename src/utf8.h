#pragma once

#include <stddef.h>
#include <stdint.h>

// Decode one Unicode scalar; malformed input consumes one byte as U+FFFD.
inline uint32_t nextCodepoint(const char *&text) {
  const auto *bytes = reinterpret_cast<const uint8_t *>(text);
  const uint8_t first = bytes[0];
  if (first < 0x80) {
    if (first) ++text;
    return first;
  }
  const int count = first >= 0xC2 && first <= 0xDF ? 2 :
                    first >= 0xE0 && first <= 0xEF ? 3 :
                    first >= 0xF0 && first <= 0xF4 ? 4 : 0;
  uint32_t value = count ? first & ((1U << (7 - count)) - 1) : 0;
  for (int i = 1; i < count; ++i) {
    if ((bytes[i] & 0xC0) != 0x80) {
      ++text;
      return 0xFFFD;
    }
    value = (value << 6) | (bytes[i] & 0x3F);
  }
  if (!count || (count == 2 && value < 0x80) ||
      (count == 3 && value < 0x800) || (count == 4 && value < 0x10000) ||
      value > 0x10FFFF || (value >= 0xD800 && value <= 0xDFFF)) {
    ++text;
    return 0xFFFD;
  }
  text += count;
  return value;
}
