#include "../src/subscription_sse.h"
#include <assert.h>
#include <stdio.h>
#include <vector>
static bool collect(const std::string &data, void *context) {
  static_cast<std::vector<std::string> *>(context)->push_back(data); return true;
}
static bool reject(const std::string &, void *) { return false; }
int main() {
  const std::string wire = ": keepalive\r\nevent: delta\r\ndata: {\"delta\":\"你好\"}\r\n\r\n"
                           "data: first\ndata:second\n\ndata: [DONE]\n\n";
  for (size_t batch = 1; batch <= wire.size(); ++batch) {
    std::vector<std::string> events;
    subscription::SSEDecoder decoder(collect, &events);
    for (size_t pos = 0; pos < wire.size(); pos += batch) {
      const size_t count = std::min(batch, wire.size() - pos);
      assert(decoder.feed(reinterpret_cast<const uint8_t *>(wire.data() + pos), count));
    }
    assert(events.size() == 3);
    assert(events[0] == "{\"delta\":\"你好\"}");
    assert(events[1] == "first\nsecond");
    assert(events[2] == "[DONE]");
  }
  std::vector<std::string> events;
  subscription::SSEDecoder truncated(collect, &events);
  const std::string partial = "data: incomplete";
  assert(truncated.feed(reinterpret_cast<const uint8_t *>(partial.data()), partial.size()));
  assert(events.empty()); // Never dispatch an unterminated/truncated event.
  subscription::SSEDecoder tooLong(collect, &events);
  const std::string oversized(32769, 'a');
  assert(!tooLong.feed(reinterpret_cast<const uint8_t *>(oversized.data()), oversized.size()));
  subscription::SSEDecoder rejected(reject, nullptr);
  const std::string event = "data: stop\n\n";
  assert(!rejected.feed(reinterpret_cast<const uint8_t *>(event.data()), event.size()));
  assert(!rejected.feed(reinterpret_cast<const uint8_t *>(event.data()), event.size()));
  puts("Subscription SSE framing tests passed.");
}
