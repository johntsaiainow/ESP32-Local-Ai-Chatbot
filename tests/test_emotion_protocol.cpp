#include "../src/emotion_protocol.h"
#include <cassert>
#include <cstring>

int main() {
  for (const auto &mood : osiris_emotion::moods) {
    const std::string input = std::string(mood.emoji) + "\xEF\xB8\x8F\r\n你好🙂，這是測試。";
    for (size_t chunk = 1; chunk <= input.size(); ++chunk) {
      osiris_emotion::Decoder decoder;
      std::string spoken, collected;
      for (size_t offset = 0; offset < input.size(); offset += chunk) {
        assert(decoder.feed(input.substr(offset, chunk), spoken));
        collected += spoken;
      }
      assert(decoder.finish());
      assert(!std::strcmp(decoder.mood->name, mood.name));
      assert(decoder.text == "你好，這是測試。");
      assert(collected == decoder.text);
    }
  }
  for (const std::string input : {"No prefix\nHello", "🙂🙂\nHello", "🙂", "🙂\n", "🙂\n😎"}) {
    osiris_emotion::Decoder decoder;
    std::string spoken;
    const bool fed = decoder.feed(input, spoken);
    assert(!fed || !decoder.finish());
    assert(spoken.empty());
  }
  for (const std::string &invalid : {std::string("\xC0\xAF"), std::string("\xED\xA0\x80"),
                                  std::string("\xF4\x90\x80\x80"), std::string("\0", 1)}) {
    osiris_emotion::Decoder decoder;
    std::string spoken;
    assert(!decoder.feed("🙂\n" + invalid, spoken));
    assert(!decoder.finish());
  }
  osiris_emotion::Decoder decoder;
  std::string spoken;
  assert(decoder.feed("🙂\n\xE4", spoken));
  assert(!decoder.finish());
}
