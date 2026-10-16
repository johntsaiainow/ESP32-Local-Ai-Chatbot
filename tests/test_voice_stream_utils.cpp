#include "../src/voice_stream_utils.h"
#include <cassert>
#include <vector>
#include <cstring>
using namespace osiris_voice;
static bool sentence(const std::string &s, void *context) {
  static_cast<std::vector<std::string> *>(context)->push_back(s); return true;
}
int main() {
  const std::string text = "你好。Temperature is 3.14 degrees. 次の文です！Final";
  for (size_t chunk = 1; chunk <= text.size(); ++chunk) {
    std::vector<std::string> out;
    Sentences splitter(sentence, &out);
    for (size_t at=0; at<text.size(); at+=chunk) assert(splitter.feed(text.substr(at, chunk)));
    assert(splitter.finish()); assert(out.size() == 4);
    std::string joined; for (auto &s : out) joined += s;
    assert(joined == text); assert(out[1] == "Temperature is 3.14 degrees.");
  }
  std::vector<std::string> out;
  Sentences truncated(sentence, &out);
  assert(truncated.feed("\xe4\xbd")); assert(!truncated.finish());
  Sentences longText(sentence, &out);
  assert(longText.feed(std::string(1000, 'a'))); assert(longText.finish());
  for (auto &s : out) assert(s.size() <= 223);
  const int16_t source[] = {0, 1000, 2000, -3000, -2000, -1000, 32767, -32768, 32767};
  uint8_t bytes[sizeof(source)];
  for (size_t n=0; n<sizeof(source)/2; ++n) { bytes[n*2] = source[n]&255; bytes[n*2+1] = uint16_t(source[n])>>8; }
  const std::vector<int16_t> expected{0, 1500, -3000, -1500, 32767, 0};
  for (size_t chunk=1; chunk<=sizeof(bytes); ++chunk) {
    PCM24to16 pcm; std::vector<int16_t> samples;
    for (size_t at=0; at<sizeof(bytes); at+=chunk)
      assert(pcm.feed(bytes+at, std::min(chunk, sizeof(bytes)-at), [&](int16_t v){samples.push_back(v); return true;}));
    assert(pcm.complete()); assert(samples == expected);
  }
  PCM24to16 odd;
  assert(odd.feed(bytes, 1, [](int16_t){return true;})); assert(!odd.complete());
}
