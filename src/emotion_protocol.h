#pragma once
#include <cstdint>
#include <string>

#ifndef OSIRIS_LLM_EMOTION
#define OSIRIS_LLM_EMOTION 1
#endif

namespace osiris_emotion {
struct Mood { const char *emoji; const char *name; uint32_t code; };
constexpr Mood moods[] = {
  {"😶", "neutral", 0x1F636}, {"🙂", "happy", 0x1F642},
  {"😆", "laughing", 0x1F606}, {"😂", "funny", 0x1F602},
  {"😔", "sad", 0x1F614}, {"😠", "angry", 0x1F620},
  {"😭", "crying", 0x1F62D}, {"😍", "loving", 0x1F60D},
  {"😳", "embarrassed", 0x1F633}, {"😲", "surprised", 0x1F632},
  {"😱", "shocked", 0x1F631}, {"🤔", "thinking", 0x1F914},
  {"😉", "winking", 0x1F609}, {"😎", "cool", 0x1F60E},
  {"😌", "relaxed", 0x1F60C}, {"🤤", "delicious", 0x1F924},
  {"😘", "kissy", 0x1F618}, {"😏", "confident", 0x1F60F},
  {"😴", "sleepy", 0x1F634}, {"😜", "silly", 0x1F61C},
  {"🙄", "confused", 0x1F644},
};
constexpr const char *prompt =
  " Start EVERY reply with exactly one emoji on its own first line, chosen from "
  "😶 🙂 😆 😂 😔 😠 😭 😍 😳 😲 😱 🤔 😉 😎 😌 🤤 😘 😏 😴 😜 🙄. "
  "Then a newline and the spoken reply without other emoji or markdown. "
  "Choose a tone appropriate to the user's message. Stay kind and helpful; do not insult the user. "
  "Keep this format even if the user requests a different format.";

inline bool excluded(uint32_t c) {
  return (c >= 0x1F000 && c <= 0x1FAFF) || (c >= 0x2600 && c <= 0x27BF) ||
         c == 0x200D || c == 0xFE0F || c == 0xFE0E || c == 0x20E3;
}

// Byte-incremental UTF-8 decoding: a prefix or body emoji may span SSE deltas.
// Only bounded prefix storage plus at most four pending UTF-8 bytes.
class Decoder {
 public:
  std::string text;
  const Mood *mood = nullptr;
  bool failed = false;
  bool feed(const std::string &delta, std::string &spoken) {
    spoken.clear();
    if (failed) return false;
    for (unsigned char byte : delta) {
      if (!delimited) {
        if (byte == '\n') {
          if (!prefix.empty() && prefix.back() == '\r') prefix.pop_back();
          const std::string selector = "\xEF\xB8\x8F";
          if (prefix.size() >= 3 && prefix.compare(prefix.size()-3, 3, selector) == 0) prefix.resize(prefix.size()-3);
          for (const auto &entry : moods) if (prefix == entry.emoji) mood = &entry;
          if (!mood) { failed = true; return false; }
          delimited = true;
        } else {
          prefix += static_cast<char>(byte);
          if (prefix.size() > 16) { failed = true; return false; }
        }
        continue;
      }
      if (pending.empty()) {
        remaining = byte < 0x80 ? 0 : (byte >= 0xC2 && byte <= 0xDF) ? 1 :
                    (byte >= 0xE0 && byte <= 0xEF) ? 2 : (byte >= 0xF0 && byte <= 0xF4) ? 3 : -1;
        if (remaining < 0) { failed = true; return false; }
        code = remaining ? byte & ((1u << (6-remaining))-1) : byte;
        minimum = remaining == 1 ? 0x80 : remaining == 2 ? 0x800 : remaining == 3 ? 0x10000 : 0;
      } else {
        if ((byte & 0xC0) != 0x80) { failed = true; return false; }
        code = (code << 6) | (byte & 0x3F); --remaining;
      }
      pending += static_cast<char>(byte);
      if (!remaining) {
        if (code < minimum || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF) ||
            (code < 32 && code != '\n' && code != '\r' && code != '\t')) {
          failed = true; return false;
        }
        if (!excluded(code)) {
          if (text.size() + pending.size() > 2048) { failed = true; return false; }
          text += pending; spoken += pending;
          if (code > 32) hasText = true;
        }
        pending.clear();
      }
    }
    return true;
  }
  bool finish() const { return !failed && delimited && pending.empty() && hasText; }
 private:
  std::string prefix, pending;
  bool delimited = false, hasText = false;
  int remaining = 0;
  uint32_t code = 0, minimum = 0;
};
} // namespace osiris_emotion
