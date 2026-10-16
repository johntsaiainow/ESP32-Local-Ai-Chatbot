#pragma once
#include "subscription_sse.h"

bool subscriptionVerified = false;
String subscriptionValidatedModel;

bool subscriptionHTTP(const String &url, const String &body, bool tokenEndpoint,
                      CloudBuffer &response, int &status) {
  if (time(nullptr) < 1700000000) { cloudError = "Waiting for network time (OAuth TLS)."; return false; }
  WiFiClientSecure tls;
  tls.setCACertBundle(cloudCABundleStart, cloudCABundleEnd - cloudCABundleStart);
  HTTPClient http;
  http.setConnectTimeout(15000); http.setTimeout(60000); http.setReuse(false);
  if (!http.begin(tls, url)) { cloudError = "OAuth HTTPS initialization failed."; return false; }
  if (tokenEndpoint) http.addHeader("Content-Type", "application/x-www-form-urlencoded");
  else http.addHeader("Authorization", "Bearer " + subscriptionAccess);
  status = tokenEndpoint ? http.POST(body) : http.GET();
  bool ok = status == 200;
  if (ok) {
    const int expected = http.getSize(); const int received = http.writeToStream(&response);
    ok = received > 0 && (expected < 0 || received == expected);
  }
  http.end();
  if (!ok) cloudError = "ChatGPT OAuth HTTP " + String(status) + ". Import fresh app credentials if expired/revoked.";
  return ok;
}
String subscriptionFormEncode(const String &value) {
  const char hex[] = "0123456789ABCDEF"; String result;
  result.reserve(value.length() * 3);
  for (unsigned char ch : value) {
    if (isalnum(ch) || ch == '-' || ch == '_' || ch == '.' || ch == '~') result += char(ch);
    else { result += '%'; result += hex[ch >> 4]; result += hex[ch & 15]; }
  }
  return result;
}
bool refreshSubscription(bool force = false) {
  const int64_t now = time(nullptr);
  if (!force && subscriptionExpiry > now + 90) return true; // Catalog/inference validates imported bearer credentials.
  if (now < 1700000000) { cloudError = "Waiting for network time (OAuth)."; return false; }
  if (subscriptionRefresh.isEmpty() || subscriptionClient.isEmpty()) {
    cloudError = "Import device-specific ChatGPT OAuth credentials in Setup."; return false;
  }
  if (subscriptionEarliestRefresh > now) {
    if (subscriptionExpiry > now + 5) return true; // The catalog/inference server validates imported access.
    cloudError = "OAuth refresh not allowed yet; try later."; return false;
  }
  const String body = "grant_type=refresh_token&client_id=" + subscriptionFormEncode(subscriptionClient) +
    "&refresh_token=" + subscriptionFormEncode(subscriptionRefresh) + "&resource=https%3A%2F%2Fapi.openai.com%2Fv1";
  CloudBuffer response(32768); int status = 0;
  if (!subscriptionHTTP("https://auth.openai.com/api/accounts/oauth/token", body, true, response, status)) return false;
  JsonDocument json(&cloudJsonAllocator);
  if (deserializeJson(json, reinterpret_cast<char *>(response.data), response.size)) {
    cloudError = "Invalid OAuth refresh response."; return false;
  }
  const String access = json["access_token"] | "";
  const String refresh = json["refresh_token"] | "";
  const String scope = json["scope"] | "";
  const String granted = " " + scope + " ";
  const int64_t lifetime = json["expires_in"] | int64_t(0);
  if (access.isEmpty() || refresh.isEmpty() || lifetime <= 0 || lifetime > 86400 ||
      granted.indexOf(" chatgpt.tokens.use.direct ") < 0 || granted.indexOf(" resource.invoke ") < 0) {
    cloudError = "OAuth refresh missing ChatGPT plan grants/tokens. Reauthorize this app."; return false;
  }
  JsonDocument saved(&cloudJsonAllocator);
  saved["access_token"] = access; saved["refresh_token"] = refresh;
  saved["client_id"] = subscriptionClient; saved["scope"] = scope;
  saved["expires_at"] = now + lifetime;
  saved["earliest_refresh_at"] = json["earliest_refresh_at"] | int64_t(0);
  String serialized; serializeJson(saved, serialized);
  if (saved.overflowed() || !saveSubscriptionJSON(serialized, true)) {
    cloudError = "Cannot persist rotated OAuth credentials; reauthorize if needed."; return false;
  }
  subscriptionVerified = true;
  subscriptionValidatedModel = "";
  return true;
}
bool validateSubscriptionModel() {
  if (subscriptionValidatedModel == cloudChatModel && cloudChatModel.length()) return true;
  CloudBuffer response(128 * 1024); int status = 0;
  if (!subscriptionHTTP("https://api.openai.com/v1/models", "", false, response, status)) return false;
  JsonDocument json(&cloudJsonAllocator);
  if (deserializeJson(json, reinterpret_cast<char *>(response.data), response.size)) {
    cloudError = "Invalid subscription model catalog."; return false;
  }
  for (JsonObject model : json["models"].as<JsonArray>()) {
    const String slug = model["slug"] | "";
    if (String(model["visibility"] | "") != "list" || !cloudModelValid(slug)) continue;
    if (cloudChatModel.isEmpty()) { cloudChatModel = slug; chatModelParam.setValue(slug.c_str(), 96); }
    if (slug == cloudChatModel) { subscriptionValidatedModel = slug; subscriptionVerified = true; return true; }
  }
  cloudError = "Chat model not in this subscription's catalog. Clear chat model for auto-selection.";
  return false;
}
class SubscriptionStream : public Stream {
 public:
  String reply;
  bool complete = false, failed = false;
  size_t total = 0;
  subscription::SSEDecoder decoder;
  SubscriptionStream() : decoder(event, this) {}
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }
  void flush() override {}
  size_t write(uint8_t ch) override { return write(&ch, 1); }
  size_t write(const uint8_t *data, size_t count) override {
    if (failed || count > 512 * 1024 - total) { failed = true; return 0; }
    total += count;
    if (!decoder.feed(data, count)) { failed = true; return 0; }
    return count;
  }
  static bool event(const std::string &data, void *context) {
    auto &stream = *static_cast<SubscriptionStream *>(context);
    if (data == "[DONE]") return true;
    JsonDocument json(&cloudJsonAllocator);
    if (deserializeJson(json, data.c_str(), data.size())) return false;
    const String type = json["type"] | "";
    if (type == "response.output_text.delta") {
      if (!json["delta"].is<const char *>()) return false;
      const String delta = json["delta"].as<String>();
      if (stream.reply.length() + delta.length() > 2048) return false;
      stream.reply += delta;
    } else if (type == "response.completed") {
      stream.complete = String(json["response"]["status"] | "") == "completed";
      if (!stream.complete) return false;
    } else if (type == "response.failed" || type == "response.incomplete" || type == "error") return false;
    return true;
  }
};
String subscriptionReply(JsonDocument &request) {
  if (!refreshSubscription() || !validateSubscriptionModel()) return "";
  request["model"] = cloudChatModel; request["stream"] = true; request["store"] = false;
  String body;
  if (request.overflowed() || !body.reserve(measureJson(request) + 1) || !serializeJson(request, body)) {
    cloudError = "No memory for subscription request."; return "";
  }
  for (unsigned attempt = 0; attempt < 2; ++attempt) {
    WiFiClientSecure tls;
    tls.setCACertBundle(cloudCABundleStart, cloudCABundleEnd - cloudCABundleStart);
    HTTPClient http;
    http.setConnectTimeout(15000); http.setTimeout(60000); http.setReuse(false);
    if (!http.begin(tls, "https://api.openai.com/v1/responses")) {
      cloudError = "Cannot connect to ChatGPT Responses."; return "";
    }
    http.addHeader("Authorization", "Bearer " + subscriptionAccess);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Accept", "text/event-stream");
    const int status = http.POST(body);
    if (status == 401 && attempt == 0) {
      http.end(); if (!refreshSubscription(true)) return ""; continue;
    }
    if (status != 200) {
      http.end(); cloudError = "ChatGPT subscription HTTP " + String(status) +
        ". Check plan grants/quota/model. No API fallback was made."; return "";
    }
    SubscriptionStream stream;
    const int received = http.writeToStream(&stream); http.end();
    if (received <= 0 || stream.failed || !stream.complete || stream.reply.isEmpty()) {
      cloudError = "Subscription stream failed, blocked, oversized or incomplete."; return "";
    }
    return stream.reply;
  }
  return "";
}
