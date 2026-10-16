#pragma once
#include <atomic>
#include "voice_stream_utils.h"
extern std::atomic<uint32_t> cloudFirstAudio;
// HTTP producer and I2S consumer share a bounded PSRAM ring. A short prefill
// absorbs Wi-Fi jitter; the HTTP callback never writes directly into I2S.
class CloudPCMStream : public Stream {
 public:
  static constexpr size_t CAPACITY = 96 * 1024, PREFILL = 12000, LIMIT = 2 * 1024 * 1024;
  uint8_t *ring = nullptr;
  std::atomic<size_t> written{0}, readAt{0};
  std::atomic<bool> eof{false}, abort{false}, done{true}, failed{false};
  std::atomic<uint32_t> firstAudio{0}, underruns{0};
  bool start() {
    ring = static_cast<uint8_t *>(ps_malloc(CAPACITY));
    if (!ring) return false;
    done = false;
    if (xTaskCreate(task, "cloud-pcm", 6144, this, 3, nullptr) != pdPASS) { done = true; free(ring); ring = nullptr; return false; }
    return true;
  }
  bool finish(bool success) {
    if (!success) abort = true;
    eof = true;
    while (!done.load()) delay(1);
    return success && !failed && written > 0 && written % 2 == 0;
  }
  ~CloudPCMStream() { abort = true; eof = true; while (!done.load()) delay(1); free(ring); }
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
  size_t write(uint8_t ch) override { return write(&ch, 1); }
  size_t write(const uint8_t *data, size_t count) override {
    if (count > LIMIT - written.load()) return 0;
    size_t offset = 0; uint32_t progress = millis();
    while (offset < count && !abort && !failed) {
      const size_t w = written.load(), freeBytes = CAPACITY - (w - readAt.load());
      if (!freeBytes) { if (millis()-progress > 60000) { failed = true; break; } delay(1); continue; }
      const size_t batch = min(count-offset, min(freeBytes, CAPACITY-w%CAPACITY));
      memcpy(ring+w%CAPACITY, data+offset, batch); written.store(w+batch);
      offset += batch; progress = millis();
    }
    return offset;
  }
 private:
  static void task(void *context) {
    auto &s = *static_cast<CloudPCMStream *>(context);
    while (!s.abort && !s.eof && s.written < PREFILL) delay(1);
    osiris_voice::PCM24to16 convert;
    int16_t stereo[512]; size_t used = 0;
    bool enabled = false, waiting = false;
    auto flush = [&]() {
      if (!used) return true;
      if (!enabled) { boardSpeakerEnable(true); enabled = true; }
      size_t sent = 0;
      const bool ok = boardAudioWrite(stereo, used*sizeof(int16_t), &sent, 200) == ESP_OK && sent == used*sizeof(int16_t);
      if (ok && !s.firstAudio.load()) {
        s.firstAudio = millis();
        if (!cloudFirstAudio.load()) cloudFirstAudio = s.firstAudio.load();
      }
      used = 0; return ok;
    };
    while (!s.abort && !s.failed) {
      const size_t r = s.readAt.load(), available = s.written.load()-r;
      if (!available) {
        if (s.eof) break;
        if (enabled && !waiting) { ++s.underruns; waiting = true; }
        delay(1); continue;
      }
      waiting = false;
      const size_t batch = min(size_t(1536), min(available, CAPACITY-r%CAPACITY));
      const bool ok = convert.feed(s.ring+r%CAPACITY, batch, [&](int16_t sample) {
        stereo[used++] = sample; stereo[used++] = sample;
        return used != 512 || flush();
      });
      s.readAt.store(r+batch);
      if (!ok) { s.failed = true; break; }
    }
    if (!s.abort && !s.failed && (!convert.complete() || !flush())) s.failed = true;
    if (enabled) { delay(110); boardSpeakerEnable(false); }
    s.done.store(true); vTaskDelete(nullptr);
  }
};
