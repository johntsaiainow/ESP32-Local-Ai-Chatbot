#pragma once
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>
#include <time.h>
#include "cloud_voice_utils.h"

extern const uint8_t cloudCABundleStart[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t cloudCABundleEnd[] asm("_binary_x509_crt_bundle_end");
struct CloudJsonAllocator : ArduinoJson::Allocator {
  void *allocate(size_t n) override { return heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT); }
  void deallocate(void *p) override { free(p); }
  void *reallocate(void *p, size_t n) override { return heap_caps_realloc(p, n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT); }
};
CloudJsonAllocator cloudJsonAllocator;
// HTTPClient.writeToStream decodes HTTP chunk framing; all downloads are bounded.
class CloudBuffer : public Stream {
 public:
  uint8_t *data = nullptr; size_t size = 0, capacity = 0, limit;
  explicit CloudBuffer(size_t maximum = 2 * 1024 * 1024) : limit(maximum) {}
  ~CloudBuffer() { free(data); }
  CloudBuffer(const CloudBuffer &) = delete;
  CloudBuffer &operator=(const CloudBuffer &) = delete;
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
  size_t write(uint8_t ch) override { return write(&ch, 1); }
  size_t write(const uint8_t *bytes, size_t count) override {
    if (count > limit - size) return 0;
    if (size + count + 1 > capacity) {
      const size_t grown = min(limit + 1, max(size + count + 1, max(size_t(4096), capacity * 2)));
      auto *next = static_cast<uint8_t *>(heap_caps_realloc(data, grown, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
      if (!next) return 0;
      data = next; capacity = grown;
    }
    memcpy(data + size, bytes, count); size += count; data[size] = 0; return count;
  }
};
String cloudError;
String cloudHistoryUser[4], cloudHistoryReply[4];
size_t cloudHistoryCount = 0;
uint8_t *cloudCapture = nullptr;
size_t cloudCaptured = 0;
bool cloudCapturing = false, cloudSpeakingSeen = false;
uint32_t cloudCaptureStart = 0, cloudNextAttempt = 0;
uint32_t cloudAwakeStart = 0, cloudAwakeDuration = 0;
SpeechGate cloudGate(80, 16000);
int16_t cloudPreroll[4096]; size_t cloudPrerollAt = 0, cloudPrerollCount = 0;

void cloudScreen(const String &state, const String &text) {
  remoteDisplay = true; agentExpression = state; drawAgentFace();
  lcd.fillRect(104, 0, 216, 140, TFT_BLACK);
  DisplayLanguage language = DisplayLanguage::English;
  const char *scan = text.c_str();
  while (*scan) {
    const uint32_t code = nextCodepoint(scan);
    if (code >= 0x3040 && code <= 0x30FF) { language = DisplayLanguage::Japanese; break; }
    if (code >= 0x3400 && code <= 0x9FFF) language = DisplayLanguage::TraditionalChinese;
  }
  lcd.setClipRect(104, 0, 216, 140);
  printLocalizedText(106, 4, text.c_str(), language); lcd.clearClipRect();
  boardPresent(true); // Show state changes before synchronous network requests.
}
bool cloudAwake() {
  return cloudAwakeDuration && millis() - cloudAwakeStart < cloudAwakeDuration;
}
void cloudArm(uint32_t duration) { cloudAwakeStart = millis(); cloudAwakeDuration = duration; }
void cloudIdleScreen() {
  cloudScreen(cloudAwake() ? "listening" : "sleeping",
              cloudAwake() ? "Awake! Ask a follow-up." : "Say Osiris!\nCloud voice ready.");
}
void clearCloudCapture() {
  cloudCaptured = 0; cloudCapturing = false; cloudSpeakingSeen = false;
  cloudPrerollAt = cloudPrerollCount = 0; cloudGate = SpeechGate(80, 16000);
}
bool cloudModelValid(const String &model) {
  if (!model.length() || model.length() > 96) return false;
  for (char ch : model) if (!isalnum((unsigned char)ch) && ch != '-' && ch != '_' && ch != '.') return false;
  return true;
}
#include "chatgpt_subscription.h"

bool cloudReady() {
  cloudError = "";
  if (!psramFound()) cloudError = "Standalone mode needs PSRAM.";
  else if (!audioReady || !speakerReady) cloudError = "Microphone/speaker not ready.";
  else if (!(cloudMode != "gemini" ? cloudOpenAIKey : cloudGeminiKey).length()) cloudError = "Set API key in Settings.";
  else if (cloudMode == "chatgpt" && (subscriptionAccess.isEmpty() || subscriptionRefresh.isEmpty()))
    cloudError = "Import ChatGPT OAuth JSON in Setup. Speech still needs API key.";
  else if ((!(cloudMode == "chatgpt" && cloudChatModel.isEmpty()) && !cloudModelValid(cloudChatModel)) || !cloudModelValid(cloudTTSModel) ||
           (cloudMode != "gemini" && !cloudModelValid(cloudSTTModel))) cloudError = "Set valid chat/STT/TTS model IDs in Settings.";
  return cloudError.isEmpty();
}
bool cloudPost(const String &url, const char *contentType, const uint8_t *body, size_t bytes, CloudBuffer &result, String *responseType = nullptr) {
  if (time(nullptr) < 1700000000) { cloudError = "Waiting for network time (TLS)."; return false; }
  WiFiClientSecure tls;
  tls.setCACertBundle(cloudCABundleStart, cloudCABundleEnd - cloudCABundleStart);
  HTTPClient http;
  http.setConnectTimeout(15000); http.setTimeout(60000); http.setReuse(false);
  if (!http.begin(tls, url)) { cloudError = "HTTPS initialization failed."; return false; }
  const char *responseHeaders[] = {"Content-Type"};
  http.collectHeaders(responseHeaders, 1);
  http.addHeader("Content-Type", contentType);
  if (cloudMode != "gemini") http.addHeader("Authorization", "Bearer " + cloudOpenAIKey);
  else http.addHeader("x-goog-api-key", cloudGeminiKey);
  const int status = http.POST(const_cast<uint8_t *>(body), bytes);
  if (responseType) *responseType = http.header("Content-Type");
  bool ok = status == 200;
  if (ok) {
    const int expected = http.getSize();
    const int received = http.writeToStream(&result);
    ok = received > 0 && (expected < 0 || received == expected);
    if (!ok) cloudError = "Cloud download failed/too large.";
  } else cloudError = "Cloud HTTP " + String(status) + ". Check key, models, quota and WiFi.";
  http.end(); return ok;
}
bool cloudJSON(const String &url, JsonDocument &request, CloudBuffer &response, JsonDocument &json) {
  String body;
  if (request.overflowed() || !body.reserve(measureJson(request) + 1) || !serializeJson(request, body)) {
    cloudError = "Not enough memory for API request."; return false;
  }
  if (!cloudPost(url, "application/json", reinterpret_cast<const uint8_t *>(body.c_str()), body.length(), response)) return false;
  const auto error = deserializeJson(json, reinterpret_cast<char *>(response.data), response.size);
  if (error) { cloudError = "Invalid/oversized cloud JSON."; return false; }
  return true;
}
String geminiURL(const String &model) {
  return "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent";
}
String geminiText(JsonDocument &json) {
  if (String(json["candidates"][0]["finishReason"] | "") != "STOP") {
    cloudError = "Gemini reply blocked/incomplete."; return "";
  }
  String text;
  for (JsonObject part : json["candidates"][0]["content"]["parts"].as<JsonArray>()) {
    if (!(part["thought"] | false) && part["text"].is<const char *>()) text += part["text"].as<const char *>();
  }
  return text;
}
String cloudBase64(const uint8_t *data, size_t bytes) {
  const size_t capacity = ((bytes + 2) / 3) * 4 + 1;
  auto *encoded = static_cast<unsigned char *>(ps_malloc(capacity));
  if (!encoded) { cloudError = "Not enough PSRAM for audio."; return ""; }
  size_t written = 0;
  const int status = mbedtls_base64_encode(encoded, capacity, &written, data, bytes);
  String output = status == 0 ? String(reinterpret_cast<char *>(encoded), written) : "";
  free(encoded); return output;
}
String cloudTranscribe() {
  cloud_voice::wavHeader(cloudCapture, cloudCaptured);
  const size_t wavSize = cloudCaptured + 44;
  CloudBuffer response(128 * 1024);
  JsonDocument json(&cloudJsonAllocator);
  if (cloudMode != "gemini") {
    const String boundary = "box3AudioBoundary8c191";
    const String prefix = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n" + cloudSTTModel +
      "\r\n--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\nContent-Type: audio/wav\r\n\r\n";
    const String suffix = "\r\n--" + boundary + "--\r\n";
    CloudBuffer request(MAX_AUDIO_BYTES + 2048);
    if (request.write(reinterpret_cast<const uint8_t *>(prefix.c_str()), prefix.length()) != prefix.length() ||
        request.write(cloudCapture, wavSize) != wavSize ||
        request.write(reinterpret_cast<const uint8_t *>(suffix.c_str()), suffix.length()) != suffix.length()) {
      cloudError = "No memory for transcription."; return "";
    }
    if (!cloudPost("https://api.openai.com/v1/audio/transcriptions", ("multipart/form-data; boundary=" + boundary).c_str(),
                   request.data, request.size, response)) return "";
    if (deserializeJson(json, reinterpret_cast<char *>(response.data), response.size)) { cloudError = "Invalid transcript JSON."; return ""; }
    return String(json["text"] | "");
  }
  JsonDocument request(&cloudJsonAllocator);
  auto parts = request["contents"][0]["parts"].to<JsonArray>();
  parts.add<JsonObject>()["text"] = "Transcribe only the spoken words verbatim, preserving language. Do not answer. Return empty text for silence.";
  JsonObject audio = parts.add<JsonObject>()["inlineData"].to<JsonObject>();
  audio["mimeType"] = "audio/wav";
  audio["data"] = cloudBase64(cloudCapture, wavSize);
  if (!cloudError.isEmpty() || !cloudJSON(geminiURL(cloudChatModel), request, response, json)) return "";
  return geminiText(json);
}
String cloudReply(const String &text) {
  const char *instructions = "You are Osiris. Reply in the same language as the current user; use Traditional Chinese for Chinese. "
    "Keep spoken replies under 35 words. No markdown or emoji. You have no web, weather, code execution or device tools. Never invent live facts.";
  JsonDocument request(&cloudJsonAllocator), json(&cloudJsonAllocator);
  CloudBuffer response(128 * 1024);
  if (cloudMode != "gemini") {
    request["model"] = cloudChatModel; request["instructions"] = instructions; request["store"] = false;
    auto input = request["input"].to<JsonArray>();
    for (size_t n = 0; n < cloudHistoryCount; ++n) {
      auto user = input.add<JsonObject>(); user["role"] = "user"; user["content"] = cloudHistoryUser[n];
      auto reply = input.add<JsonObject>(); reply["role"] = "assistant"; reply["content"] = cloudHistoryReply[n];
    }
    auto user = input.add<JsonObject>(); user["role"] = "user"; user["content"] = text;
    if (cloudMode == "chatgpt") return subscriptionReply(request);
    if (!cloudJSON("https://api.openai.com/v1/responses", request, response, json)) return "";
    if (String(json["status"] | "") != "completed") { cloudError = "OpenAI reply incomplete/blocked."; return ""; }
    String reply;
    for (JsonObject item : json["output"].as<JsonArray>()) {
      if (String(item["type"] | "") != "message") continue;
      for (JsonObject part : item["content"].as<JsonArray>())
        if (String(part["type"] | "") == "output_text") reply += part["text"].as<String>();
    }
    return reply;
  }
  request["systemInstruction"]["parts"][0]["text"] = instructions;
  auto input = request["contents"].to<JsonArray>();
  for (size_t n = 0; n < cloudHistoryCount; ++n) {
    auto user = input.add<JsonObject>(); user["role"] = "user"; user["parts"][0]["text"] = cloudHistoryUser[n];
    auto reply = input.add<JsonObject>(); reply["role"] = "model"; reply["parts"][0]["text"] = cloudHistoryReply[n];
  }
  auto user = input.add<JsonObject>(); user["role"] = "user"; user["parts"][0]["text"] = text;
  if (!cloudJSON(geminiURL(cloudChatModel), request, response, json)) return "";
  return geminiText(json);
}
bool cloudPlayPCM(const cloud_voice::PCM &pcm) {
  if (!pcm.bytes || pcm.bytes % 2 || pcm.rate < 8000 || pcm.rate > 48000) { cloudError = "Unsupported PCM format."; return false; }
  boardSpeakerEnable(true);
  const size_t sourceFrames = pcm.bytes / 2;
  const size_t outputFrames = sourceFrames * 16000ULL / pcm.rate;
  bool ok = true;
  for (size_t offset = 0; offset < outputFrames && ok;) {
    int16_t stereo[512]; const size_t count = min(size_t(256), outputFrames - offset);
    for (size_t n = 0; n < count; ++n) {
      const uint64_t position = uint64_t(offset + n) * pcm.rate;
      const size_t index = position / 16000;
      const size_t next = min(index + 1, sourceFrames - 1);
      const int a = int16_t(pcm.data[index * 2] | uint16_t(pcm.data[index * 2 + 1]) << 8);
      const int b = int16_t(pcm.data[next * 2] | uint16_t(pcm.data[next * 2 + 1]) << 8);
      const int value = a + (b - a) * int(position % 16000) / 16000;
      stereo[n * 2] = stereo[n * 2 + 1] = value;
    }
    size_t sent = 0;
    ok = boardAudioWrite(stereo, count * 4, &sent, 200) == ESP_OK && sent == count * 4;
    offset += count; delay(1);
  }
  delay(110); boardSpeakerEnable(false);
  if (!ok) cloudError = "Speaker I2S write failed.";
  return ok;
}
bool cloudSpeak(const String &reply) {
  JsonDocument request(&cloudJsonAllocator), json(&cloudJsonAllocator);
  CloudBuffer response;
  if (cloudMode != "gemini") {
    request["model"] = cloudTTSModel; request["input"] = reply;
    request["voice"] = cloudVoice.length() ? cloudVoice : "alloy"; request["response_format"] = "pcm";
    String body, mime;
    if (request.overflowed() || !body.reserve(measureJson(request) + 1) || !serializeJson(request, body)) {
      cloudError = "No memory for speech request."; return false;
    }
    if (!cloudPost("https://api.openai.com/v1/audio/speech", "application/json",
                   reinterpret_cast<const uint8_t *>(body.c_str()), body.length(), response, &mime)) return false;
    mime.toLowerCase();
    if (!mime.startsWith("audio/") && !mime.startsWith("application/octet-stream")) {
      cloudError = "OpenAI returned non-audio speech data."; return false;
    }
    return cloudPlayPCM({response.data, response.size, 24000});
  }
  request["contents"][0]["parts"][0]["text"] = reply;
  request["generationConfig"]["responseModalities"][0] = "AUDIO";
  const String voice = cloudVoice.length() ? cloudVoice : "Kore";
  if (cloudTTSModel.startsWith("gemini-2"))
    request["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] = voice;
  else request["generationConfig"]["speechConfig"]["voiceConfig"]["voice"] = voice;
  if (!cloudJSON(geminiURL(cloudTTSModel), request, response, json)) return false;
  if (String(json["candidates"][0]["finishReason"] | "") != "STOP") {
    cloudError = "Gemini speech blocked/incomplete."; return false;
  }
  for (JsonObject part : json["candidates"][0]["content"]["parts"].as<JsonArray>()) {
    const char *encoded = part["inlineData"]["data"] | "";
    if (!*encoded) continue;
    String mime = part["inlineData"]["mimeType"] | ""; mime.toLowerCase();
    const size_t capacity = strlen(encoded) / 4 * 3 + 4;
    if (capacity > 2 * 1024 * 1024) break;
    auto *decoded = static_cast<uint8_t *>(ps_malloc(capacity)); size_t bytes = 0;
    if (!decoded) { cloudError = "No memory for speech playback."; return false; }
    const bool decodedOK = mbedtls_base64_decode(decoded, capacity, &bytes,
                            reinterpret_cast<const unsigned char *>(encoded), strlen(encoded)) == 0;
    cloud_voice::PCM pcm{decoded, bytes, 24000};
    bool valid = decodedOK;
    if (valid && bytes >= 4 && !memcmp(decoded, "RIFF", 4)) valid = cloud_voice::parseWav(decoded, bytes, pcm);
    else if (valid) {
      valid = mime.startsWith("audio/l16") || mime.startsWith("audio/pcm");
      const int rate = mime.indexOf("rate=");
      if (rate >= 0) pcm.rate = mime.substring(rate + 5).toInt();
    }
    const bool ok = valid && cloudPlayPCM(pcm); free(decoded);
    if (!ok && cloudError.isEmpty()) cloudError = "Unsupported Gemini audio format.";
    return ok;
  }
  cloudError = "Gemini returned no speech audio."; return false;
}
void processCloudUtterance(bool alreadyAwake) {
  cloudError = ""; cloudScreen("thinking", "Transcribing speech...");
  String text = cloudTranscribe(); text.trim();
  if (!cloudError.isEmpty()) return;
  const size_t wake = cloud_voice::wakeOffset(text.c_str());
  if (wake != SIZE_MAX) {
    text = text.substring(wake); text.trim();
    while (text.startsWith("!") || text.startsWith(",") || text.startsWith(":") || text.startsWith(".") ||
           text.startsWith("！") || text.startsWith("，") || text.startsWith("。") ||
           text.startsWith("?") || text.startsWith("？") || text.startsWith("：") ||
           text.startsWith(";") || text.startsWith("；") || text.startsWith("-") || text.startsWith("—")) {
      text.remove(0, static_cast<unsigned char>(text[0]) >= 0x80 ? 3 : 1); text.trim();
    }
    if (text.isEmpty()) { cloudArm(15000); return; }
  } else if (!alreadyAwake || text.isEmpty()) return;
  if (text.length() > 1024) { cloudError = "Request too long. Try a shorter question."; return; }
  cloudScreen("thinking", "Asking " + cloudMode + "...");
  String reply = cloudReply(text); reply.trim();
  if (reply.isEmpty() || reply.length() > 2048) {
    if (cloudError.isEmpty()) cloudError = "Empty/oversized cloud reply."; return;
  }
  cloudScreen("speaking", reply);
  if (!cloudSpeak(reply)) return;
  if (cloudHistoryCount == 4) {
    for (size_t n = 1; n < 4; ++n) { cloudHistoryUser[n - 1] = cloudHistoryUser[n]; cloudHistoryReply[n - 1] = cloudHistoryReply[n]; }
    --cloudHistoryCount;
  }
  cloudHistoryUser[cloudHistoryCount] = text; cloudHistoryReply[cloudHistoryCount++] = reply;
  cloudArm(30000);
}
void resetDirectCloud() {
  clearCloudCapture(); cloudHistoryCount = 0; cloudAwakeDuration = 0;
  subscriptionVerified = false; subscriptionValidatedModel = "";
  for (size_t n = 0; n < 4; ++n) { cloudHistoryUser[n] = ""; cloudHistoryReply[n] = ""; }
  free(cloudCapture); cloudCapture = nullptr;
  if (directCloudEnabled()) {
    if (psramFound()) heap_caps_malloc_extmem_enable(4096);
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    cloudNextAttempt = millis(); cloudIdleScreen();
  }
}
void pollDirectCloud() {
  if (wifiManager.getConfigPortalActive()) { clearCloudCapture(); return; }
  if (WiFi.status() != WL_CONNECTED) { clearCloudCapture(); return; }
  if (int32_t(millis() - cloudNextAttempt) < 0) return;
  if (!cloudReady()) {
    cloudScreen("warning", cloudError); cloudNextAttempt = millis() + 5000; return;
  }
  if (!cloudCapture) cloudCapture = static_cast<uint8_t *>(ps_malloc(MAX_AUDIO_BYTES + 44));
  if (!cloudCapture) { cloudScreen("error", "No recording memory."); cloudNextAttempt = millis() + 5000; return; }
  static bool lastAwake = false;
  if (lastAwake != cloudAwake()) { lastAwake = cloudAwake(); cloudIdleScreen(); }
  int16_t stereo[512]; size_t received = 0;
  const esp_err_t status = boardAudioRead(stereo, sizeof(stereo), &received, 0);
  if (status != ESP_OK && status != ESP_ERR_TIMEOUT) { clearCloudCapture(); return; }
  const size_t frames = received / 4;
  if (!frames) return;
  int mean = 0;
  for (size_t n = 0; n < frames; ++n) {
    const int16_t value = stereo[n * 2]; mean += abs(int(value));
    if (!cloudCapturing) {
      cloudPreroll[cloudPrerollAt] = value; cloudPrerollAt = (cloudPrerollAt + 1) % 4096;
      cloudPrerollCount = min(cloudPrerollCount + 1, size_t(4096));
    } else if (cloudCaptured + 2 <= MAX_AUDIO_BYTES) {
      cloudCapture[44 + cloudCaptured++] = value & 255;
      cloudCapture[44 + cloudCaptured++] = uint16_t(value) >> 8;
    }
  }
  cloudGate.feed(mean / frames, frames);
  if (!cloudCapturing && cloudGate.started) {
    cloudCapturing = true; cloudCaptureStart = millis(); cloudSpeakingSeen = cloudAwake();
    const size_t first = (cloudPrerollAt + 4096 - cloudPrerollCount) % 4096;
    for (size_t n = 0; n < cloudPrerollCount; ++n) {
      const int16_t value = cloudPreroll[(first + n) % 4096];
      cloudCapture[44 + cloudCaptured++] = value & 255;
      cloudCapture[44 + cloudCaptured++] = uint16_t(value) >> 8;
    }
  }
  updateVolumeMeter(stereo, received / 2, 2, cloudCapturing);
  if (cloudCapturing && (cloudGate.finished || cloudCaptured >= MAX_AUDIO_BYTES || millis() - cloudCaptureStart >= 10000)) {
    processCloudUtterance(cloudSpeakingSeen);
    clearCloudCapture();
    // Drain stale DMA samples after blocking HTTP/playback, avoiding self-wake.
    for (unsigned n = 0; n < 32; ++n) {
      size_t drained = 0; boardAudioRead(stereo, sizeof(stereo), &drained, 0);
      if (!drained) break;
    }
    if (cloudError.length()) { cloudScreen("error", cloudError); cloudNextAttempt = millis() + 5000; }
    else cloudIdleScreen();
  }
}
