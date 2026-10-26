#pragma once
// Only this worker accesses speaker/I2S. UI and model receiving stay on main.
class CloudSentenceQueue {
 public:
  struct Sentence { char text[225]; };
  QueueHandle_t queue = nullptr;
  std::atomic<bool> stopped{false}, done{true}, failed{false};
  String error;
  uint32_t firstText = 0;
  osiris_voice::Sentences splitter;
  osiris_emotion::Decoder emotion;
  CloudSentenceQueue() : splitter(emit, this) {}
  bool start() {
    cloudFirstAudio = 0;
    queue = xQueueCreate(16, sizeof(Sentence));
    if (!queue) return false;
    done = false;
    if (xTaskCreate(task, "cloud-speech", 16384, this, 2, nullptr) != pdPASS) {
      done = true; vQueueDelete(queue); queue = nullptr; return false;
    }
    return true;
  }
  static bool delta(const String &text, void *context) {
    auto &s = *static_cast<CloudSentenceQueue *>(context);
    if (!s.firstText) s.firstText = millis();
    // This callback runs inside HTTP/SSE/JSON frames. PNG/font rendering here
    // can exhaust loopTask's stack; render only after cloudReply unwinds.
    if (s.failed) return false;
#if OSIRIS_LLM_EMOTION
    std::string spoken;
    if (!s.emotion.feed(text.c_str(), spoken)) {
      s.error = "Invalid emotion prefix or reply text."; s.failed = true; return false;
    }
    return s.splitter.feed(spoken);
#else
    return s.splitter.feed(text.c_str());
#endif
  }
  static bool emit(const std::string &text, void *context) {
    auto &s = *static_cast<CloudSentenceQueue *>(context);
    if (text.size() >= sizeof(Sentence::text) || s.failed) return false;
    Sentence sentence{}; memcpy(sentence.text, text.data(), text.size());
    return xQueueSend(s.queue, &sentence, pdMS_TO_TICKS(60000)) == pdTRUE && !s.failed;
  }
  bool finish(bool success) {
    if (success && !splitter.finish()) success = false;
    if (!success) stopped = true;
    Sentence end{};
    while (!done && xQueueSend(queue, &end, pdMS_TO_TICKS(100)) != pdTRUE) {}
    while (!done.load()) delay(1);
    return success && !failed;
  }
  ~CloudSentenceQueue() {
    if (!done) finish(false);
    if (queue) vQueueDelete(queue);
  }
 private:
  static void task(void *context) {
    auto &s = *static_cast<CloudSentenceQueue *>(context);
    CloudPCMStream pcm;
    const bool streamingPCM = cloudMode != "gemini" ||
      (cloudTTSModel.startsWith("gemini-") && cloudTTSModel.substring(7).toFloat() >= 3.1f);
    bool pcmStarted = false;
    Sentence sentence;
    while (!s.stopped && xQueueReceive(s.queue, &sentence, portMAX_DELAY) == pdTRUE) {
      if (!sentence.text[0]) break;
      // Leave internal task/PSRAM headroom for the initial TLS handshake.
      if (streamingPCM && !pcmStarted) {
        if (!pcm.start()) { s.error = "No memory/task for streaming speech."; s.failed = true; break; }
        pcmStarted = true;
      }
      if (!cloudSpeak(sentence.text, s.error, streamingPCM ? &pcm : nullptr)) { s.failed = true; break; }
    }
    if (pcmStarted && !pcm.finish(!s.failed && !s.stopped)) {
      s.failed = true;
      if (s.error.isEmpty()) s.error = "Speech playback incomplete.";
    }
    Serial.printf("VOICE task=speech stack_free=%u internal_free=%u\n",
      (unsigned)uxTaskGetStackHighWaterMark(nullptr), (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    free(pcm.ring); pcm.ring = nullptr;
    s.done = true; vTaskDelete(nullptr);
  }
};
