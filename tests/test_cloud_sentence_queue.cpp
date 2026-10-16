// Run the real sentence-worker lifecycle with a local queue/task adapter.
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
class String : public std::string {
 public:
  using std::string::string; using std::string::operator=;
  bool isEmpty() const { return empty(); }
  bool startsWith(const char *s) const { return compare(0, strlen(s), s) == 0; }
  String substring(size_t pos) const { return String(c_str()+pos); }
  float toFloat() const { return std::strtof(c_str(), nullptr); }
};
using uint8_t = unsigned char;
constexpr int pdPASS=1, pdTRUE=1, portMAX_DELAY=-1, MALLOC_CAP_INTERNAL=1, MALLOC_CAP_8BIT=2;
int pdMS_TO_TICKS(int ms) { return ms; }
uint32_t millis() { return 1; }
void delay(unsigned ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
unsigned uxTaskGetStackHighWaterMark(void *) { return 8192; }
unsigned heap_caps_get_free_size(int) { return 64000; }
struct Console { template<class... Args> void printf(const char *, Args...) {} } Serial;
struct Queue { size_t capacity, size; std::mutex mutex; std::condition_variable cv; std::deque<std::vector<uint8_t>> items; };
using QueueHandle_t = Queue *;
QueueHandle_t xQueueCreate(size_t count, size_t size) { auto *q=new Queue; q->capacity=count; q->size=size; return q; }
void vQueueDelete(QueueHandle_t q) { delete q; }
int xQueueSend(QueueHandle_t q, const void *data, int timeout) {
  std::unique_lock<std::mutex> lock(q->mutex);
  if (!q->cv.wait_for(lock, std::chrono::milliseconds(timeout), [&]{ return q->items.size()<q->capacity; })) return 0;
  const auto *p=static_cast<const uint8_t *>(data); q->items.emplace_back(p,p+q->size); q->cv.notify_all(); return pdTRUE;
}
int xQueueReceive(QueueHandle_t q, void *data, int) {
  std::unique_lock<std::mutex> lock(q->mutex); q->cv.wait(lock,[&]{return !q->items.empty();});
  memcpy(data,q->items.front().data(),q->size); q->items.pop_front(); q->cv.notify_all(); return pdTRUE;
}
int xTaskCreate(void (*task)(void *), const char *, unsigned, void *context, int, void *) { std::thread(task,context).detach(); return pdPASS; }
void vTaskDelete(void *) {}
#include "../src/voice_stream_utils.h"
std::atomic<uint32_t> cloudFirstAudio{0};
std::atomic<unsigned> starts{0}, finishes{0}, spoken{0};
bool startAllowed=true;
class CloudPCMStream {
 public:
  uint8_t *ring=nullptr;
  bool start() { ++starts; return startAllowed; }
  bool finish(bool success) { ++finishes; return success; }
};
String cloudMode="openai", cloudTTSModel="test";
bool cloudSpeak(const String &, String &, CloudPCMStream *pcm) { assert(pcm); ++spoken; return true; }
#include "../src/cloud_sentence_queue.h"
int main() {
  { // Failed/cancelled model before first sentence must not allocate PCM resources.
    CloudSentenceQueue queue; assert(queue.start()); assert(!queue.finish(false));
    assert(starts==0); assert(finishes==0); assert(spoken==0);
  }
  {
    CloudSentenceQueue queue; assert(queue.start());
    assert(CloudSentenceQueue::delta("你好。第二句。", &queue));
    assert(queue.finish(true));
    assert(starts==1); assert(finishes==1); assert(spoken==2);
  }
  {
    startAllowed=false;
    CloudSentenceQueue queue; assert(queue.start());
    CloudSentenceQueue::delta("Hello. ", &queue);
    assert(!queue.finish(true)); assert(queue.failed);
    assert(!queue.error.isEmpty()); assert(spoken==2);
  }
}
