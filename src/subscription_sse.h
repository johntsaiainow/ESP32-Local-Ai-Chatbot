#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string>

namespace subscription {
// Incremental SSE framing, independent of packet boundaries and HTTP chunking.
class SSEDecoder {
 public:
  using Callback = bool (*)(const std::string &, void *);
  explicit SSEDecoder(Callback callback, void *context, size_t limit = 32768) : callback_(callback), context_(context), limit_(limit) {}
  bool feed(const uint8_t *bytes, size_t size) {
    if (failed_) return false;
    for (size_t n = 0; n < size; ++n) {
      const char ch = bytes[n];
      if (ch == '\r') continue;
      if (ch != '\n') {
        if (line_.size() >= limit_) return fail();
        line_ += ch; continue;
      }
      if (line_.empty()) {
        if (!event_.empty() && !callback_(event_, context_)) return fail();
        event_.clear();
      } else if (line_.compare(0, 5, "data:") == 0) {
        const size_t first = line_.size() > 5 && line_[5] == ' ' ? 6 : 5;
        if (event_.size() + line_.size() - first + 1 > limit_) return fail();
        if (!event_.empty()) event_ += '\n';
        event_ += line_.substr(first);
      }
      line_.clear();
    }
    return true;
  }
 private:
  bool fail() { failed_ = true; return false; }
  Callback callback_; void *context_; bool failed_ = false;
  std::string line_, event_; size_t limit_;
};
} // namespace subscription
