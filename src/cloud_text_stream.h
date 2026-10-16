#pragma once
#include "subscription_sse.h"
class CloudTextStream : public Stream {
 public:
  enum Kind { Responses, Chat, Gemini };
  Kind kind; CloudDelta delta; void *context;
  String reply; bool complete = false, failed = false, done = false;
  size_t total = 0;
  subscription::SSEDecoder decoder;
  CloudTextStream(Kind k, CloudDelta cb, void *user) : kind(k), delta(cb), context(user), decoder(event, this) {}
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
  size_t write(uint8_t ch) override { return write(&ch, 1); }
  size_t write(const uint8_t *data, size_t count) override {
    if (failed || count > 512*1024-total) { failed = true; return 0; }
    total += count;
    if (!decoder.feed(data, count)) { failed = true; return 0; }
    return count;
  }
  static bool event(const std::string &data, void *user) {
    auto &s = *static_cast<CloudTextStream *>(user);
    if (data == "[DONE]") { s.done = true; return s.kind == Chat && s.complete; }
    JsonDocument json(&cloudJsonAllocator);
    if (deserializeJson(json, data.c_str(), data.size()) || json["error"].is<JsonObject>()) return false;
    const bool wasComplete = s.complete;
    String text;
    if (s.kind == Responses) {
      const String type = json["type"] | "";
      if (type == "response.output_text.delta") text = json["delta"] | "";
      else if (type == "response.completed") {
        s.complete = String(json["response"]["status"] | "") == "completed"; return s.complete;
      } else if (type == "error" || type == "response.failed" || type == "response.incomplete" || type.startsWith("response.refusal")) return false;
    } else if (s.kind == Chat) {
      auto choice = json["choices"][0];
      if (!choice["delta"]["tool_calls"].isNull() || !choice["delta"]["refusal"].isNull()) return false;
      text = choice["delta"]["content"] | "";
      if (!choice["finish_reason"].isNull()) {
        if (String(choice["finish_reason"] | "") != "stop") return false;
        s.complete = true;
      }
    } else {
      if (!json["promptFeedback"]["blockReason"].isNull()) return false;
      auto candidate = json["candidates"][0];
      for (JsonObject part : candidate["content"]["parts"].as<JsonArray>())
        if (!(part["thought"] | false)) text += part["text"] | "";
      if (!candidate["finishReason"].isNull()) {
        if (String(candidate["finishReason"] | "") != "STOP") return false;
        s.complete = true;
      }
    }
    if (text.length()) {
      if (wasComplete || s.reply.length()+text.length() > 2048) return false;
      s.reply += text;
      if (s.delta && !s.delta(text, s.context)) return false;
    }
    return true;
  }
};
String cloudStreamJSON(const String &url, JsonDocument &request, CloudTextStream::Kind kind,
                       CloudDelta delta, void *context) {
  String body;
  if (request.overflowed() || !body.reserve(measureJson(request)+1) || !serializeJson(request, body)) {
    cloudError = "No memory for streaming model request."; return "";
  }
  CloudBuffer unused(1); CloudTextStream stream(kind, delta, context);
  if (!cloudPost(url, "application/json", reinterpret_cast<const uint8_t *>(body.c_str()), body.length(), unused, nullptr, &stream) ||
      !stream.complete || stream.failed) {
    if (cloudError.isEmpty()) cloudError = "Model stream failed or incomplete.";
    return "";
  }
  return stream.reply;
}
