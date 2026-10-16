#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>

namespace cloud_voice {
inline uint32_t le32(const uint8_t *p) {
  return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}
inline void put32(uint8_t *p, uint32_t n) {
  for (unsigned i = 0; i < 4; ++i) p[i] = (n >> (8 * i)) & 255;
}
inline void wavHeader(uint8_t *out, uint32_t bytes) {
  memset(out, 0, 44);
  memcpy(out, "RIFF", 4); put32(out + 4, bytes + 36);
  memcpy(out + 8, "WAVEfmt ", 8); put32(out + 16, 16);
  out[20] = 1; out[22] = 1; put32(out + 24, 16000); put32(out + 28, 32000);
  out[32] = 2; out[34] = 16; memcpy(out + 36, "data", 4); put32(out + 40, bytes);
}
struct PCM { const uint8_t *data; size_t bytes; uint32_t rate; };
inline bool parseWav(const uint8_t *data, size_t bytes, PCM &pcm) {
  if (bytes < 12 || memcmp(data, "RIFF", 4) || memcmp(data + 8, "WAVE", 4)) return false;
  bool format = false; uint32_t rate = 0;
  for (size_t pos = 12; pos <= bytes && bytes - pos >= 8;) {
    const size_t count = le32(data + pos + 4);
    const uint8_t *chunk = data + pos; pos += 8;
    if (count > bytes - pos) return false;
    if (!memcmp(chunk, "fmt ", 4)) {
      if (count < 16 || data[pos] != 1 || data[pos + 1] || data[pos + 2] != 1 ||
          data[pos + 3] || data[pos + 14] != 16 || data[pos + 15]) return false;
      rate = le32(data + pos + 4); format = rate >= 8000 && rate <= 48000;
    } else if (!memcmp(chunk, "data", 4)) {
      if (!format || !count || count % 2) return false;
      pcm = {data + pos, count, rate}; return true;
    }
    if (count + (count & 1u) > bytes - pos) return false;
    pos += count + (count & 1u);
  }
  return false;
}
inline bool wordByte(unsigned char ch) { return isalnum(ch) || ch == '_'; }
// Returns the first byte after the whole wake word; SIZE_MAX means no match.
inline size_t wakeOffset(const char *text) {
  const size_t size = strlen(text); const char *word = "osiris";
  for (size_t pos = 0; pos + 6 <= size; ++pos) {
    if (pos && wordByte((unsigned char)text[pos - 1])) continue;
    bool matches = true;
    for (size_t n = 0; n < 6; ++n) if (tolower((unsigned char)text[pos + n]) != word[n]) matches = false;
    if (matches && (pos + 6 == size || !wordByte((unsigned char)text[pos + 6]))) return pos + 6;
  }
  return SIZE_MAX;
}
} // namespace cloud_voice
