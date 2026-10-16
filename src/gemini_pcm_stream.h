#pragma once
// Gemini 3.1+ TTS streams base64 PCM chunks in SSE. Older TTS stays buffered.
class GeminiPCMStream : public Stream {
 public:
  CloudPCMStream &pcm;
  subscription::SSEDecoder decoder;
  bool complete = false, failed = false;
  size_t total = 0;
  explicit GeminiPCMStream(CloudPCMStream &output) : pcm(output), decoder(event, this, 192*1024) {}
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
  size_t write(uint8_t ch) override { return write(&ch, 1); }
  size_t write(const uint8_t *data, size_t count) override {
    if (failed || count > 4*1024*1024-total) { failed = true; return 0; }
    total += count;
    if (!decoder.feed(data, count)) { failed = true; return 0; }
    return count;
  }
  static bool event(const std::string &data, void *context) {
    auto &s = *static_cast<GeminiPCMStream *>(context);
    JsonDocument json(&cloudJsonAllocator);
    if (deserializeJson(json, data.c_str(), data.size()) || !json["error"].isNull() ||
        !json["promptFeedback"]["blockReason"].isNull()) return false;
    auto candidate = json["candidates"][0];
    if (!candidate["finishReason"].isNull()) {
      if (String(candidate["finishReason"] | "") != "STOP") return false;
      s.complete = true;
    }
    for (JsonObject part : candidate["content"]["parts"].as<JsonArray>()) {
      const char *encoded = part["inlineData"]["data"] | "";
      if (!*encoded) continue;
      String mime = part["inlineData"]["mimeType"] | ""; mime.toLowerCase();
      if (!mime.startsWith("audio/l16") && !mime.startsWith("audio/pcm")) return false;
      int rate = mime.indexOf("rate=");
      if (rate >= 0 && mime.substring(rate+5).toInt() != 24000) return false;
      const size_t capacity = strlen(encoded)/4*3+4;
      if (capacity > 144*1024) return false;
      uint8_t *decoded = static_cast<uint8_t *>(ps_malloc(capacity)); size_t count = 0;
      if (!decoded) return false;
      const bool ok = mbedtls_base64_decode(decoded, capacity, &count,
                        reinterpret_cast<const unsigned char *>(encoded), strlen(encoded)) == 0 &&
                      !(count >= 4 && !memcmp(decoded, "RIFF", 4)) && s.pcm.write(decoded, count) == count;
      free(decoded); if (!ok) return false;
    }
    return true;
  }
};
