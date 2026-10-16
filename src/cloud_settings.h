#pragma once
#include <Preferences.h>
#include <ArduinoJson.h>
#include "wake_phrase.h"

String cloudMode = "host", cloudOpenAIKey, cloudGeminiKey;
String cloudChatModel, cloudSTTModel = "gpt-4o-mini-transcribe", cloudTTSModel, cloudVoice;
bool cloudSettingsChanged = false;
String wakePhrase = "Osiris", wakeSettingError;
// Extra form capacity lets validation reject long multibyte input instead of
// silently accepting a phrase truncated to a valid UTF-8 prefix.
constexpr int WAKE_FORM_BYTES = 384;
WiFiManagerParameter wakePhraseParam("wake_phrase", "Wake phrase (blank resets to Osiris; max 96 UTF-8 bytes)", "Osiris", WAKE_FORM_BYTES);
String subscriptionAccess, subscriptionRefresh, subscriptionClient, subscriptionScope;
int64_t subscriptionExpiry = 0, subscriptionEarliestRefresh = 0;
String subscriptionCredentialError;
WiFiManagerParameter subscriptionNotice(
  "<p><b>ChatGPT subscription (experimental)</b>: import OAuth credentials issued for this device/app. "
  "There is no browser login on ESP32. This is NOT an account password or browser cookie. "
  "Speech still needs an OpenAI API key. Never paste credentials into chat.</p>");
WiFiManagerParameter subscriptionParam("chatgpt_oauth", "OAuth JSON (blank keeps saved; - signs out)", "", 8192,
                                      "type=\"password\" autocomplete=\"new-password\"");

WiFiManagerParameter cloudModeParam("cloud_mode", "Mode: host / openai / gemini / chatgpt", "host", 8);
WiFiManagerParameter openAIKeyParam("openai_key", "OpenAI API key (blank keeps saved; - clears)", "", 256,
                                   "type=\"password\" autocomplete=\"new-password\"");
WiFiManagerParameter geminiKeyParam("gemini_key", "Gemini API key (blank keeps saved; - clears)", "", 256,
                                   "type=\"password\" autocomplete=\"new-password\"");
WiFiManagerParameter chatModelParam("chat_model", "Chat model ID (Gemini must accept audio)", "", 96);
WiFiManagerParameter sttModelParam("stt_model", "OpenAI transcription model", "gpt-4o-mini-transcribe", 96);
WiFiManagerParameter ttsModelParam("tts_model", "Speech model ID (must support TTS)", "", 96);
WiFiManagerParameter voiceParam("cloud_voice", "Voice (blank: OpenAI alloy / Gemini Kore)", "", 64);

bool directCloudEnabled() { return cloudMode == "openai" || cloudMode == "gemini" || cloudMode == "chatgpt"; }
bool saveSubscriptionJSON(const String &value, bool persist) {
  JsonDocument json;
  if (value.length() > 8192 || deserializeJson(json, value)) {
    subscriptionCredentialError = "Invalid OAuth JSON (maximum 8192 bytes)."; return false;
  }
  const String access = json["access_token"] | "";
  const String refresh = json["refresh_token"] | "";
  const String client = json["client_id"] | "";
  if (!access.length() || !refresh.length() || !client.startsWith("oaiapp_") || client.length() > 128 ||
      access.length() > 6000 || refresh.length() > 2048) {
    subscriptionCredentialError = "OAuth needs access_token, refresh_token and issued oaiapp_ client_id."; return false;
  }
  String scope = json["scope"] | "";
  if (scope.isEmpty()) for (JsonVariant entry : json["scopes"].as<JsonArray>()) {
    if (scope.length()) scope += ' ';
    scope += entry.as<String>();
  }
  // Imported scope is only a hint. Refresh/model/inference endpoints enforce grants.
  if (persist) {
    Preferences prefs;
    if (!prefs.begin("chatgpt-oauth", false)) { subscriptionCredentialError = "Cannot save OAuth credentials."; return false; }
    JsonDocument saved;
    saved["access_token"] = access; saved["refresh_token"] = refresh;
    saved["client_id"] = client; saved["scope"] = scope;
    saved["expires_at"] = json["expires_at"] | int64_t(0);
    saved["earliest_refresh_at"] = json["earliest_refresh_at"] | int64_t(0);
    String normalized;
    if (saved.overflowed() || !serializeJson(saved, normalized)) {
      prefs.end(); subscriptionCredentialError = "No memory to save OAuth credentials."; return false;
    }
    const size_t written = prefs.putString("credentials", normalized); prefs.end();
    if (!written) { subscriptionCredentialError = "OAuth storage write failed."; return false; }
  }
  subscriptionAccess = access; subscriptionRefresh = refresh; subscriptionClient = client;
  subscriptionScope = scope;
  subscriptionExpiry = json["expires_at"] | int64_t(0);
  subscriptionEarliestRefresh = json["earliest_refresh_at"] | int64_t(0);
  subscriptionCredentialError = ""; return true;
}
void loadSubscriptionCredentials() {
  Preferences prefs;
  if (!prefs.begin("chatgpt-oauth", true)) return;
  String saved = prefs.getString("credentials", ""); prefs.end();
  if (saved.length()) saveSubscriptionJSON(saved, false);
}
void clearSubscriptionCredentials() {
  Preferences prefs;
  if (prefs.begin("chatgpt-oauth", false)) { prefs.remove("credentials"); prefs.end(); }
  subscriptionAccess = subscriptionRefresh = subscriptionClient = subscriptionScope = "";
  subscriptionExpiry = subscriptionEarliestRefresh = 0;
}
void loadCloudSettings() {
  Preferences prefs;
  if (prefs.begin("cloud-voice", true)) {
    cloudMode = prefs.getString("mode", "host");
    cloudOpenAIKey = prefs.getString("openai_key", "");
    cloudGeminiKey = prefs.getString("gemini_key", "");
    cloudChatModel = prefs.getString("chat", "");
    cloudSTTModel = prefs.getString("stt", "gpt-4o-mini-transcribe");
    cloudTTSModel = prefs.getString("tts", "");
    cloudVoice = prefs.getString("voice", "");
    std::string phrase;
    const String saved = prefs.getString("wake_phrase", "Osiris");
    wakePhrase = osiris_wake::normalize(saved.c_str(), phrase) ? phrase.c_str() : "Osiris";
    prefs.end();
  }
  cloudModeParam.setValue(cloudMode.c_str(), 8);
  chatModelParam.setValue(cloudChatModel.c_str(), 96);
  sttModelParam.setValue(cloudSTTModel.c_str(), 96);
  ttsModelParam.setValue(cloudTTSModel.c_str(), 96);
  voiceParam.setValue(cloudVoice.c_str(), 64);
  wakePhraseParam.setValue(wakePhrase.c_str(), WAKE_FORM_BYTES);
}
void saveCloudSettings() {
  std::string phrase;
  if (!osiris_wake::normalize(wakePhraseParam.getValue(), phrase)) {
    wakeSettingError = "Wake phrase: use 1-96 UTF-8 bytes, without quotes or < > &.";
    wakePhraseParam.setValue(wakePhrase.c_str(), WAKE_FORM_BYTES);
    return;
  }
  String mode = cloudModeParam.getValue(); mode.trim(); mode.toLowerCase();
  if (mode != "host" && mode != "openai" && mode != "gemini" && mode != "chatgpt") {
    Serial.println("Cloud mode must be host, openai, gemini, or chatgpt; settings not saved."); return;
  }
  String credentials = subscriptionParam.getValue(); credentials.trim();
  subscriptionParam.setValue("", 8192);
  if (credentials == "-") clearSubscriptionCredentials();
  else if (credentials.length() && !saveSubscriptionJSON(credentials, true)) {
    Serial.println("OAuth credential import failed; cloud settings not changed."); return;
  }
  Preferences prefs;
  if (!prefs.begin("cloud-voice", false)) return;
  if (!prefs.putString("wake_phrase", phrase.c_str())) {
    prefs.end(); wakeSettingError = "Could not save wake phrase. Please try again."; return;
  }
  prefs.putString("mode", mode);
  wakeSettingError = "";
  for (auto *param : {&openAIKeyParam, &geminiKeyParam}) {
    String key = param->getValue(); key.trim();
    if (key.length()) prefs.putString(param == &openAIKeyParam ? "openai_key" : "gemini_key", key == "-" ? "" : key);
    param->setValue("", 256); // Never echo credentials back into the portal.
  }
  prefs.putString("chat", chatModelParam.getValue());
  prefs.putString("stt", sttModelParam.getValue());
  prefs.putString("tts", ttsModelParam.getValue());
  prefs.putString("voice", voiceParam.getValue()); prefs.end();
  loadCloudSettings(); cloudSettingsChanged = true;
}
void setupCloudSettings() {
  loadCloudSettings(); loadSubscriptionCredentials();
  for (auto *param : {&cloudModeParam, &openAIKeyParam, &geminiKeyParam, &chatModelParam,
                      &sttModelParam, &ttsModelParam, &voiceParam, &wakePhraseParam, &subscriptionNotice, &subscriptionParam}) wifiManager.addParameter(param);
  wifiManager.setSaveParamsCallback(saveCloudSettings);
}
