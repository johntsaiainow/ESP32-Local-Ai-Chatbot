#pragma once
#include <string>
#include "utf8.h"

namespace osiris_wake {
constexpr size_t MAX_BYTES = 96;
inline bool separator(uint32_t c) {
  return c == ' ' || c == '\t' || c == '\r' || c == '\n' ||
         c == '!' || c == '.' || c == ',' || c == '?' || c == ':' || c == ';' ||
         c == 0xFF01 || c == 0x3002 || c == 0xFF0C || c == 0xFF1F || c == 0xFF1A || c == 0xFF1B;
}
// Trim surrounding sentence punctuation, validate UTF-8 and keep the saved
// phrase bounded. Blank input restores the factory default; punctuation alone
// must never become an empty keyword that matches all speech.
inline bool normalize(const char *input, std::string &result) {
  const char *scan = input, *first = nullptr, *last = nullptr;
  bool hasText = false;
  while (*scan) {
    const char *start = scan;
    const uint32_t code = nextCodepoint(scan);
    if (code == 0xFFFD || code == '<' || code == '>' || code == '"' || code == '\'' || code == '&' ||
        (code < 32 && code != '\t' && code != '\r' && code != '\n') || code == 127) return false;
    if (!separator(code)) {
      if (!first) first = start;
      last = scan;
      hasText |= (code >= 'a' && code <= 'z') || (code >= 'A' && code <= 'Z') ||
                 (code >= '0' && code <= '9') || code >= 128;
    }
  }
  if (!first) {
    // Only actual whitespace, not punctuation, means reset.
    for (scan = input; *scan; ++scan) if (*scan != ' ' && *scan != '\t' && *scan != '\r' && *scan != '\n') return false;
    result = "Osiris"; return true;
  }
  if (!hasText || size_t(last - first) > MAX_BYTES) return false;
  result.assign(first, last);
  for (char &c : result) if (c == '\t' || c == '\r' || c == '\n') c = ' ';
  return true;
}
} // namespace osiris_wake
