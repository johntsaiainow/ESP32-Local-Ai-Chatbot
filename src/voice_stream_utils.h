#pragma once
#include <string>
#include <stdint.h>
namespace osiris_voice {
// UTF-8 remains intact even when network deltas split a codepoint.
class Sentences {
 public:
  using Emit = bool (*)(const std::string &, void *);
  Sentences(Emit emit, void *context) : emit_(emit), context_(context) {}
  bool feed(const std::string &delta) {
    for (unsigned char c : delta) {
      if (asciiEnd_ && (c == ' ' || c == '\n') && !flush()) return false;
      asciiEnd_ = false;
      pending_ += char(c);
      // Only split at complete UTF-8 boundaries.
      if (remaining_) { if ((c & 0xc0) != 0x80) return false; --remaining_; }
      else if (c >= 0xf0 && c <= 0xf4) remaining_ = 3;
      else if (c >= 0xe0 && c <= 0xef) remaining_ = 2;
      else if (c >= 0xc2 && c <= 0xdf) remaining_ = 1;
      else if (c >= 0x80) return false;
      if (remaining_) continue;
      asciiEnd_ = c == '.' || c == '!' || c == '?';
      const bool cjkEnd = ends("。") || ends("！") || ends("？") || ends("；");
      if (cjkEnd || c == '\n' || (pending_.size() >= 120 && c == ' ') || pending_.size() >= 220)
        if (!flush()) return false;
    }
    return true;
  }
  bool finish() { return remaining_ == 0 && flush(); }
 private:
  bool ends(const std::string &suffix) const {
    return pending_.size() >= suffix.size() && pending_.compare(pending_.size()-suffix.size(), suffix.size(), suffix) == 0;
  }
  bool flush() {
    asciiEnd_ = false;
    if (pending_.find_first_not_of(" \r\n\t") == std::string::npos) { pending_.clear(); return true; }
    if (!emit_(pending_, context_)) return false;
    pending_.clear(); return true;
  }
  Emit emit_; void *context_; std::string pending_; unsigned remaining_ = 0; bool asciiEnd_ = false;
};
// Incremental 24 kHz PCM16LE -> 16 kHz. Retains both byte and interpolation phase.
class PCM24to16 {
 public:
  template<class Emit> bool feed(const uint8_t *data, size_t count, Emit emit) {
    for (size_t n = 0; n < count; ++n) {
      if (!half_) { low_ = data[n]; half_ = true; continue; }
      const int16_t value = int16_t(uint16_t(low_) | uint16_t(data[n]) << 8); half_ = false;
      if (phase_ == 0) { if (!emit(value)) return false; }
      else if (phase_ == 1) previous_ = value;
      else if (!emit(int16_t((int(previous_) + int(value)) / 2))) return false;
      phase_ = (phase_ + 1) % 3;
    }
    return true;
  }
  bool complete() const { return !half_; }
 private:
  unsigned phase_ = 0; bool half_ = false; uint8_t low_ = 0; int16_t previous_ = 0;
};
}
