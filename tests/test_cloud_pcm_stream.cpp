// Exercise the real network/I2S ring concurrently using a host FreeRTOS shim.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
#include <cassert>
using std::min;
class Stream {
 public:
  virtual ~Stream() = default;
  virtual int available() = 0; virtual int read() = 0; virtual int peek() = 0;
  virtual void flush() = 0; virtual size_t write(uint8_t) = 0;
  virtual size_t write(const uint8_t *, size_t) = 0;
};
static auto epoch = std::chrono::steady_clock::now();
uint32_t millis() { return 1+std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-epoch).count(); }
void delay(unsigned ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void *ps_malloc(size_t size) { return std::malloc(size); }
constexpr int pdPASS = 1, ESP_OK = 0;
int xTaskCreate(void (*task)(void *), const char *, unsigned, void *context, int, void *) {
  std::thread(task, context).detach(); return pdPASS;
}
void vTaskDelete(void *) {}
std::mutex outputMutex;
std::vector<int16_t> output;
void boardSpeakerEnable(bool) {}
int boardAudioWrite(const int16_t *data, size_t bytes, size_t *sent, unsigned) {
  std::lock_guard<std::mutex> guard(outputMutex);
  output.insert(output.end(), data, data+bytes/2); *sent = bytes;
  return ESP_OK;
}
#include "../src/cloud_pcm_stream.h"
std::atomic<uint32_t> cloudFirstAudio{0};
int main() {
  {
    CloudPCMStream pcm; assert(pcm.start());
    std::vector<uint8_t> source(300000);
    for (size_t n=0; n<source.size(); n+=2) { source[n] = 0xe8; source[n+1] = 3; }
    // Cross ring wraps, odd byte packet boundaries and multiple sentences.
    for (size_t at=0; at<source.size(); at+=8191) {
      const size_t count = min(size_t(8191), source.size()-at);
      assert(pcm.write(source.data()+at, count) == count);
    }
    assert(pcm.finish(true)); assert(pcm.firstAudio > 0);
    assert(output.size() == 200000);
    for (int16_t sample : output) assert(sample == 1000);
    assert(pcm.readAt == pcm.written);
  }
  {
    CloudPCMStream truncated; assert(truncated.start());
    assert(truncated.write(uint8_t(1)) == 1);
    assert(!truncated.finish(true));
  }
  {
    CloudPCMStream aborted; assert(aborted.start());
    assert(!aborted.finish(false)); assert(aborted.done);
  }
}
