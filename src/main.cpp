#define LGFX_USE_V1
#include <SD.h>
#include <atomic>
#if defined(OSIRIS_CORE_S3) || defined(OSIRIS_ATOM_S3R)
#include <M5Unified.h>
#else
#include <LovyanGFX.hpp>
#endif
#include <Wire.h>
#include <ESP_I2S.h>
#include <SPI.h>
#include <WiFiManager.h>
#include "utf8.h"
#include "emoji_assets.h"
#include "serial_write.h"
#include "speech_gate.h"
#include <esp_rom_crc.h>
#include <driver/i2s_std.h>

#include "boards/display.h"

WiFiManager wifiManager;
#include "cloud_settings.h"
String setupSSID;
constexpr char SETUP_PASSWORD[] = "box3setup";
constexpr uint32_t WIFI_CONNECT_MS = 15000;
uint32_t wifiStarted = 0;
bool wifiStartupPending = true;
bool agentUsesWiFi = false;
bool requestedWiFi = false;
bool hostHasUSB = false, hostHasWiFi = false;


void drawSettingsBar() {
  const lgfx::IFont *previousFont = lcd.getFont();
  lcd.setFont(&fonts::Font0);
  lcd.fillRect(0, 212, 320, 28, TFT_BLACK);
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  lcd.setCursor(4, 214);
  const bool setting = wifiManager.getConfigPortalActive();
  if (setting) {
    lcd.print(setupSSID);
    lcd.setCursor(4, 226);
    lcd.print("192.168.4.1  PW: box3setup");
  } else {
    lcd.printf("Via: %s%s", directCloudEnabled() ? cloudMode.c_str() : agentUsesWiFi ? "WiFi" : "USB",
               !directCloudEnabled() && requestedWiFi != agentUsesWiFi ? " (switch pending)" : "");
    lcd.setCursor(4, 226);
    lcd.print(WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() :
              wifiStartupPending ? "WiFi connecting..." : "WiFi offline");
    if (!directCloudEnabled() && hostHasUSB && hostHasWiFi && WiFi.status() == WL_CONNECTED) {
      lcd.fillRoundRect(194, 213, 60, 26, 4, TFT_BLUE);
      lcd.setTextColor(TFT_WHITE, TFT_BLUE);
      lcd.setCursor(199, 222);
      lcd.print("Switch");
    }
  }
  lcd.fillRoundRect(258, 213, 61, 26, 4, TFT_DARKGREY);
  lcd.setTextColor(TFT_WHITE, TFT_DARKGREY);
  lcd.setCursor(264, 222);
  lcd.print(setting ? "Exit" : "Settings");
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  lcd.setFont(previousFont);
}

void enterSettingMode() {
  wifiStartupPending = false;
  if (!wifiManager.getConfigPortalActive()) {
    wifiManager.startConfigPortal(setupSSID.c_str(), SETUP_PASSWORD);
  }
  drawSettingsBar();
}

void setupWiFi() {
  wifiManager.setDebugOutput(false); // Keep credentials off the USB log.
  wifiManager.setConfigPortalBlocking(false);
  wifiManager.setConfigPortalTimeout(180);
  wifiManager.setConnectTimeout(10);
  wifiManager.setSaveConnectTimeout(10);
  setupCloudSettings();
  std::vector<const char *> menu = {"wifi", "param", "info", "exit"};
  wifiManager.setMenu(menu);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false); // Avoid power-save wakeup latency for interactive audio.
  setupSSID = String(BOARD_AP_PREFIX) + "-Setup-" + WiFi.macAddress().substring(12);
  setupSSID.replace(":", "");
  WiFi.begin(); // Reuse credentials stored by WiFiManager in NVS.
  wifiStarted = millis();
  drawSettingsBar();
}

// Poll before USB/audio early returns so Settings remains accessible in playback.
void pollSettings() {
  boardPollInput();
  boardPresent();
  if (boardButtonHeld()) {
    if (wifiManager.getConfigPortalActive()) wifiManager.stopConfigPortal();
    else enterSettingMode();
    drawSettingsBar();
  } else if (boardButtonPressed() && !directCloudEnabled() && hostHasUSB && hostHasWiFi &&
             WiFi.status() == WL_CONNECTED && !wifiManager.getConfigPortalActive()) {
    requestedWiFi = !requestedWiFi;
    drawSettingsBar();
  }
  wifiManager.process();
  if (wifiStartupPending) {
    if (WiFi.status() == WL_CONNECTED) wifiStartupPending = false;
    else if (millis() - wifiStarted >= WIFI_CONNECT_MS) enterSettingMode();
  }
  static bool touchHeld = false;
  static uint32_t lastPress = 0;
  static uint32_t lastTouchPoll = 0;
  uint16_t x = 0, y = 0;
  const bool pollTouch = millis() - lastTouchPoll >= 20;
  const bool touched = pollTouch ? lcd.getTouch(&x, &y) : touchHeld;
  if (pollTouch) lastTouchPoll = millis();
  if (pollTouch && touched && !touchHeld && x >= 194 && y >= 212 &&
      millis() - lastPress >= 300) {
    lastPress = millis();
    if (x >= 258) {
      if (wifiManager.getConfigPortalActive()) wifiManager.stopConfigPortal();
      else enterSettingMode();
    } else if (!wifiManager.getConfigPortalActive() && hostHasUSB && hostHasWiFi &&
               WiFi.status() == WL_CONNECTED) {
      requestedWiFi = !requestedWiFi;
    }
    drawSettingsBar();
  }
  touchHeld = touched;
  static uint32_t lastDraw = 0;
  if (millis() - lastDraw >= 500) {
    drawSettingsBar();
    lastDraw = millis();
  }
}

// Render the same Noto color PNG emoji used by LovyanGFX's emoji example.
bool drawEmoji(uint32_t codepoint, int x, int y) {
  return box3_emoji::draw16(lcd, codepoint, x, y);
}

// State-driven redraws avoid a continuous animation task competing with audio.
String agentExpression = "happy";
struct AgentEmoji { const char *state; uint32_t code; };
constexpr AgentEmoji AGENT_EMOJIS[] = {
  {"happy", 0x1F600}, {"listening", 0x1F442}, {"thinking", 0x1F914},
  {"speaking", 0x1F603}, {"music", 0x1F60E}, {"sad", 0x1F622}, {"error", 0x1F635},
  {"sleeping", 0x1F634},
  {"waiting", 0x231B},
  {"surprised", 0x1F62E},
  {"love", 0x1F970},
  {"success", 0x1F389},
  {"warning", 0x26A0},
};
uint32_t agentEmojiCode(const String &state) {
  for (const auto &entry : AGENT_EMOJIS) {
    if (state == entry.state) return entry.code;
  }
  return 0;
}

void drawAgentFace() {
  const lgfx::IFont *previousFont = lcd.getFont();
  lcd.setFont(&fonts::Font0);
  lcd.fillRect(0, 0, 100, 140, TFT_BLACK);
  lcd.setTextColor(TFT_CYAN, TFT_BLACK);
  lcd.setCursor(29, 8);
  lcd.print("Osiris");
  const uint32_t emoji = agentEmojiCode(agentExpression);
  box3_emoji::draw64(lcd, emoji, 18, 31);
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  const int labelX = (100 - lcd.textWidth(agentExpression)) / 2;
  lcd.setCursor(labelX, 111);
  lcd.print(agentExpression);
  lcd.drawFastVLine(100, 0, 140, TFT_DARKGREY);
  lcd.setFont(previousFont);
}

// Select a font explicitly for each language. Text arguments use UTF-8.
enum class DisplayLanguage { English, SimplifiedChinese, TraditionalChinese, Japanese, Korean };

void printLocalizedText(int x, int y, const char *text, DisplayLanguage language) {
  const lgfx::IFont *previousFont = lcd.getFont();
  switch (language) {
    case DisplayLanguage::SimplifiedChinese: lcd.setFont(&fonts::efontCN_16); break;
    case DisplayLanguage::TraditionalChinese: lcd.setFont(&fonts::efontTW_16); break;
    case DisplayLanguage::Japanese: lcd.setFont(&fonts::efontJA_16); break;
    case DisplayLanguage::Korean: lcd.setFont(&fonts::efontKR_16); break;
    default: lcd.setFont(&fonts::Font0); break;
  }
  lcd.setCursor(x, y);
  while (*text) {
    const char *start = text;
    const uint32_t codepoint = nextCodepoint(text);
    if (codepoint == 0xFE0F || codepoint == 0xFE0E) continue;
    if (codepoint == '\n') {
      lcd.setCursor(x, lcd.getCursorY() + 18);
      continue;
    }
    const bool emoji = codepoint >= 0x1F000 || codepoint == 0x231B || codepoint == 0x2705 ||
                       codepoint == 0x274C || codepoint == 0x26A0 || codepoint == 0x2764;
    const int width = emoji ? 18 : lcd.textWidth(String(start, text - start));
    if (lcd.getCursorX() + width > lcd.width()) {
      lcd.setCursor(x, lcd.getCursorY() + 18);
    }
    if (lcd.getCursorY() + 16 > lcd.height()) break;
    if (emoji) {
      const int cursorX = lcd.getCursorX();
      const int cursorY = lcd.getCursorY();
      if (!drawEmoji(codepoint, cursorX, cursorY)) {
        lcd.drawRect(cursorX + 1, cursorY + 1, 14, 14, TFT_LIGHTGREY);
        lcd.drawLine(cursorX + 3, cursorY + 3, cursorX + 12, cursorY + 12, TFT_LIGHTGREY);
      }
      lcd.setCursor(cursorX + 18, cursorY);
    } else if (codepoint == 0xFFFD) {
      lcd.print('?');
    } else {
      lcd.write(reinterpret_cast<const uint8_t *>(start), text - start);
    }
  }
  lcd.setFont(previousFont);
}

bool audioReady = false;
bool speakerReady = false;
bool remoteDisplay = false;
#include "boards/audio.h"

// Feed the meter from the same samples used for recording, without another
// I2S read. This keeps it live while the synchronous USB handler owns capture.
void updateVolumeMeter(const int16_t *samples, size_t count, size_t stride = 2,
                       bool recording = false) {
  static int lastBarWidth = 0;
  static uint32_t lastDisplay = 0;
  static uint32_t lastSerial = 0;
  static int windowPeak = 0;
  static size_t windowSamples = 0;
  for (size_t n = 0; n < count; n += stride) {
    const int value = samples[n];
    const int amplitude = value < 0 ? -value : value;
    if (amplitude > windowPeak) windowPeak = amplitude;
    ++windowSamples;
  }
  const uint32_t now = millis();
  if (now - lastDisplay >= 50) {
    // Relative input level, not calibrated sound pressure. Full scale = 32768.
    const int volume = windowPeak * 100 / 32768;
    const int barWidth = volume * 276 / 100;
    if (barWidth != lastBarWidth) {
      const uint16_t color = volume >= 85 ? TFT_RED :
                             volume >= 60 ? TFT_YELLOW : TFT_GREEN;
      lcd.fillRect(22, 182, 276, 21, TFT_BLACK);
      if (barWidth > 0) lcd.fillRect(22, 182, barWidth, 21, color);
      lastBarWidth = barWidth;
    }
    lcd.fillRect(20, 150, 280, 28, TFT_BLACK);
    lcd.setCursor(20, 150);
    if (!audioReady) lcd.print("Mic initialization failed");
    else if (windowSamples == 0) lcd.print("Mic: no audio data");
    else lcd.printf("%s: %d%%", recording ? "Recording" : "Volume", volume);

    if (now - lastSerial >= 250) {
      Serial.printf("Volume: %d%% | Peak: %d | Samples: %u | Mic: %s\n",
                    volume, windowPeak, static_cast<unsigned>(windowSamples),
                    !audioReady ? "INIT FAILED" :
                    windowSamples == 0 ? "NO DATA" : "OK");
      lastSerial = now;
    }
    windowPeak = 0;
    windowSamples = 0;
    lastDisplay = now;
    boardPresent();
  }
}

// USB protocol v1: one bounded ASCII command per line, hex-encoded payloads.
// Audio is mono signed little-endian PCM16 at 16000 Hz. Only one command runs
// at a time. Capture/playback buffers prevent serial throughput causing gaps.
constexpr size_t MAX_AUDIO_BYTES = 320000; // Ten seconds, allocated in PSRAM.
uint8_t *playBuffer = nullptr;
size_t playExpected = 0;
size_t playReceived = 0;
uint32_t playActivity = 0;
constexpr uint32_t STREAM_IDLE_MS = 60000;
std::atomic<size_t> streamWritten{0}, streamRead{0};
std::atomic<bool> streamStop{false}, streamDone{true}, streamFailed{false};
bool streaming = false;
uint8_t lastStreamChunk[8192];
std::atomic<uint32_t> streamUnderruns{0}, streamStallMs{0};
size_t streamPrefillBytes = 64000;
size_t lastStreamOffset = 0, lastStreamLength = 0;

void playbackStreamTask(void *) {
  uint32_t lastData = millis();
  size_t previousWritten = 0;
  bool waitingForAudio = false;
  uint32_t stallStarted = 0;
  // Wi-Fi prefills 500 ms to absorb network jitter; USB keeps two seconds.
  while (!streamStop && streamWritten < min(playExpected, streamPrefillBytes)) {
    const size_t written = streamWritten.load();
    if (written != previousWritten) { lastData = millis(); previousWritten = written; }
    if (millis() - lastData > STREAM_IDLE_MS) { streamFailed = true; break; }
    delay(1);
  }
  if (!streamStop && !streamFailed) boardSpeakerEnable(true);
  while (!streamStop && !streamFailed && streamRead < playExpected) {
    const size_t offset = streamRead.load();
    const size_t available = streamWritten.load() - offset;
    if (!available) {
      if (!waitingForAudio) {
        waitingForAudio = true;
        stallStarted = millis();
        ++streamUnderruns;
      }
      if (millis() - lastData > STREAM_IDLE_MS) streamFailed = true;
      delay(1);
      continue;
    }
    if (waitingForAudio) {
      streamStallMs = streamStallMs.load() + millis() - stallStarted;
      waitingForAudio = false;
    }
    int16_t stereo[512];
    const size_t count = min(size_t(256), available / 2);
    for (size_t i = 0; i < count; ++i) {
      const size_t pos = (offset + i * 2) % MAX_AUDIO_BYTES;
      const int16_t sample = int16_t(playBuffer[pos] | (playBuffer[pos + 1] << 8));
      stereo[i * 2] = stereo[i * 2 + 1] = sample;
    }
    size_t sent = 0;
    const esp_err_t writeError = boardAudioWrite(stereo, count * 4, &sent, 200);
    if (writeError != ESP_OK || sent != count * 4) {
      streamFailed = true;
      break;
    }
    streamRead = offset + count * 2;
    lastData = millis();
  }
  if (waitingForAudio) streamStallMs = streamStallMs.load() + millis() - stallStarted;
  delay(110);
  boardSpeakerEnable(false);
  streamDone = true;
  vTaskDelete(nullptr);
}
uint8_t *recordBuffer = nullptr;
size_t recordSize = 0;
uint32_t recordActivity = 0;
uint32_t usbCommandActivity = 0;

void releaseRecording() {
  free(recordBuffer);
  recordBuffer = nullptr;
  recordSize = 0;
}

void cancelPlayback() {
  streamStop = true;
  while (!streamDone) delay(1);
  streaming = false;
  free(playBuffer);
  playBuffer = nullptr;
  playExpected = playReceived = 0;
  boardSpeakerEnable(false);
}

int hexDigit(char ch) {
  if (ch >= '0' && ch <= '9') return ch - '0';
  if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
  if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
  return -1;
}

bool decodeHex(const String &hex, uint8_t *output, size_t capacity, size_t &length) {
  length = hex.length() / 2;
  if (hex.length() % 2 || length > capacity) return false;
  for (size_t i = 0; i < length; ++i) {
    const int high = hexDigit(hex[i * 2]);
    const int low = hexDigit(hex[i * 2 + 1]);
    if (high < 0 || low < 0) return false;
    output[i] = (high << 4) | low;
  }
  return true;
}

// One TCP controller owns the protocol while connected; USB diagnostics stay local.
constexpr uint16_t AGENT_TCP_PORT = 8233;
WiFiServer agentServer(AGENT_TCP_PORT, 1);
WiFiClient agentClient;
Stream *protocolIO = &Serial;

bool sendHex(const uint8_t *bytes, size_t size) {
  static const char digits[] = "0123456789abcdef";
  // USB keeps short lines; TCP batches a complete audio block.
  char line[2059];
  while (size) {
    const size_t count = min(size, agentUsesWiFi ? size_t(1024) : size_t(64));
    memcpy(line, "BOX1 DATA ", 10);
    for (size_t i = 0; i < count; ++i) {
      line[10 + i * 2] = digits[bytes[i] >> 4];
      line[11 + i * 2] = digits[bytes[i] & 15];
    }
    line[10 + count * 2] = '\n';
    if (!writeFully(*protocolIO, reinterpret_cast<uint8_t *>(line), 11 + count * 2)) {
      return false;
    }
    bytes += count;
    size -= count;
    if (!agentUsesWiFi) delay(1);
  }
  return true;
}

bool parseCount(const String &value, size_t &count) {
  if (!value.length()) return false;
  count = 0;
  for (char ch : value) {
    if (ch < '0' || ch > '9' || count > MAX_AUDIO_BYTES / 10) return false;
    count = count * 10 + ch - '0';
    if (count > MAX_AUDIO_BYTES) return false;
  }
  return count > 0 && count % 2 == 0;
}

void listenForSpeech(int threshold, unsigned silenceMs, unsigned waitMs) {
  cancelPlayback();
  releaseRecording();
  uint8_t *audio = static_cast<uint8_t *>(ps_malloc(MAX_AUDIO_BYTES));
  if (!audio) { protocolIO->println("BOX1 ERR memory"); return; }
  // Keep 256 ms before onset so the first syllable is preserved.
  int16_t *preroll = static_cast<int16_t *>(ps_malloc(4096 * sizeof(int16_t)));
  if (!preroll) { free(audio); protocolIO->println("BOX1 ERR memory"); return; }
  size_t ringAt = 0, ringCount = 0, captured = 0;
  SpeechGate gate(threshold, silenceMs * 16);
  const uint32_t startedAt = millis();
  uint32_t speechAt = 0;
  esp_err_t error = ESP_OK;
  while (captured < MAX_AUDIO_BYTES) {
    if (!gate.started && millis() - startedAt >= waitMs) break;
    if (gate.started && millis() - speechAt > 12000) { error = ESP_ERR_TIMEOUT; break; }
    int16_t stereo[512];
    size_t received = 0;
    error = boardAudioRead(stereo, sizeof(stereo), &received, 100);
    if (received % 4 || (error != ESP_OK && error != ESP_ERR_TIMEOUT)) break;
    const size_t frames = received / 4;
    int total = 0;
    const bool wasSpeaking = gate.started;
    for (size_t i = 0; i < frames; ++i) {
      const int value = stereo[i * 2];
      total += value < 0 ? -value : value;
      if (!wasSpeaking) {
        preroll[ringAt] = value;
        ringAt = (ringAt + 1) % 4096;
        if (ringCount < 4096) ++ringCount;
      } else if (captured + 2 <= MAX_AUDIO_BYTES) {
        audio[captured++] = value & 255;
        audio[captured++] = (static_cast<uint16_t>(value) >> 8);
      }
    }
    if (frames) gate.feed(total / frames, frames);
    if (!wasSpeaking && gate.started) {
      speechAt = millis();
      const size_t first = (ringAt + 4096 - ringCount) % 4096;
      for (size_t i = 0; i < ringCount; ++i) {
        const uint16_t value = preroll[(first + i) % 4096];
        audio[captured++] = value & 255;
        audio[captured++] = value >> 8;
      }
      protocolIO->println("BOX1 EVENT speech_start");
    }
    updateVolumeMeter(stereo, received / 2, 2, gate.started);
    if (gate.finished) break;
    delay(1);
  }
  free(preroll);
  if (!gate.started && (error == ESP_OK || error == ESP_ERR_TIMEOUT)) {
    free(audio);
    protocolIO->println("BOX1 OK bytes=0 audio=pull1 reason=silence");
  } else if (!gate.started || (!gate.finished && captured < MAX_AUDIO_BYTES)) {
    free(audio);
    protocolIO->printf("BOX1 ERR listen_read error=%d\n", static_cast<int>(error));
  } else {
    recordBuffer = audio;
    recordSize = captured;
    recordActivity = millis();
    protocolIO->printf("BOX1 OK bytes=%u audio=pull1 reason=%s\n",
                  static_cast<unsigned>(captured), gate.finished ? "silence" : "limit");
  }
}

void handleCommand(const String &line) {
  if (line == "BOX1 PING") {
    protocolIO->printf("BOX1 OK mic=%d speaker=%d rate=16000 audio=pull1 capture=slot32-v3 playback=usbfast-v2 rx=4096 vad=1 upload=checked1 stream=ring1 streamrev=4 sync=1 face=1 emojistates=1 link=1 netchunk=%u netread=%u\n", audioReady, speakerReady,
                       agentUsesWiFi ? 8192u : 0u, agentUsesWiFi ? 4096u : 0u);
  } else if (line == "BOX1 LINK" || line.startsWith("BOX1 LINK ")) {
    if (line == "BOX1 LINK SET USB") requestedWiFi = false;
    else if (line == "BOX1 LINK SET WIFI") requestedWiFi = true;
    else if (line.startsWith("BOX1 LINK OPTIONS ")) {
      int usb, wifi; char extra;
      if (sscanf(line.c_str(), "BOX1 LINK OPTIONS %d %d %c", &usb, &wifi, &extra) != 2 ||
          (usb != 0 && usb != 1) || (wifi != 0 && wifi != 1)) {
        protocolIO->println("BOX1 ERR link_options"); return;
      }
      hostHasUSB = usb;
      hostHasWiFi = wifi;
    } else if (line != "BOX1 LINK") {
      protocolIO->println("BOX1 ERR link_command"); return;
    }
    protocolIO->printf("BOX1 OK transport=%s requested=%s usb=%d wifi=%d\n",
                       agentUsesWiFi ? "wifi" : "usb", requestedWiFi ? "wifi" : "usb",
                       hostHasUSB, hostHasWiFi);
    drawSettingsBar();
  } else if (line.startsWith("BOX1 LISTEN ")) {
    int threshold; unsigned silenceMs, waitMs; char extra;
    if (!audioReady || sscanf(line.c_str(), "BOX1 LISTEN %d %u %u %c",
                              &threshold, &silenceMs, &waitMs, &extra) != 3 ||
        threshold < 1 || threshold > 32768 || silenceMs < 250 || silenceMs > 5000 ||
        waitMs < 250 || waitMs > 10000) {
      protocolIO->println("BOX1 ERR listen_parameters"); return;
    }
    listenForSpeech(threshold, silenceMs, waitMs);
  } else if (line.startsWith("BOX1 FACE ")) {
    const String expression = line.substring(10);
    if (!agentEmojiCode(expression)) {
      protocolIO->println("BOX1 ERR expression"); return;
    }
    agentExpression = expression;
    drawAgentFace();
    protocolIO->println("BOX1 OK");
  } else if (line.startsWith("BOX1 TEXT ")) {
    const int split = line.indexOf(' ', 10);
    if (split < 0) { protocolIO->println("BOX1 ERR text_format"); return; }
    const String language = line.substring(10, split);
    DisplayLanguage selected;
    if (language == "en") selected = DisplayLanguage::English;
    else if (language == "zh") selected = DisplayLanguage::SimplifiedChinese;
    else if (language == "zh-TW") selected = DisplayLanguage::TraditionalChinese;
    else if (language == "ja") selected = DisplayLanguage::Japanese;
    else if (language == "ko") selected = DisplayLanguage::Korean;
    else { protocolIO->println("BOX1 ERR language"); return; }
    char text[1025];
    size_t length;
    if (!decodeHex(line.substring(split + 1), reinterpret_cast<uint8_t *>(text), 1024, length)) {
      protocolIO->println("BOX1 ERR text_hex"); return;
    }
    text[length] = 0;
    remoteDisplay = true;
    drawAgentFace();
    lcd.fillRect(104, 0, 216, 140, TFT_BLACK);
    lcd.setClipRect(104, 0, 216, 140);
    printLocalizedText(104, 4, text, selected);
    lcd.clearClipRect();
    protocolIO->println("BOX1 OK");
  } else if (line.startsWith("BOX1 SYNC ")) {
    const String token = line.substring(10);
    if (!token.length() || token.length() > 32) { protocolIO->println("BOX1 ERR sync_token"); return; }
    protocolIO->printf("\nBOX1 OK sync=%s next=%u read=%u failed=%d done=%d\n", token.c_str(),
                  static_cast<unsigned>(playReceived), static_cast<unsigned>(streamRead.load()),
                  streamFailed.load(), streamDone.load());
  } else if (line.startsWith("BOX1 RESET ")) {
    const String token = line.substring(11);
    if (!token.length() || token.length() > 32) { protocolIO->println("BOX1 ERR reset_token"); return; }
    cancelPlayback(); releaseRecording();
    protocolIO->printf("BOX1 OK sync=%s\n", token.c_str());
  } else if (line == "BOX1 CANCEL") {
    cancelPlayback(); releaseRecording(); protocolIO->println("BOX1 OK");
  } else if (line.startsWith("BOX1 READ ")) {
    const String value = line.substring(10);
    const int split = value.indexOf(' ');
    const String offsetText = split < 0 ? value : value.substring(0, split);
    size_t requested = 256; // Legacy READ offset remains compatible.
    bool valid = offsetText.length() > 0;
    if (split >= 0) {
      const String countText = value.substring(split + 1);
      char *end = nullptr;
      requested = strtoul(countText.c_str(), &end, 10);
      valid = countText.length() && countText[0] >= '0' && countText[0] <= '9' &&
              !*end && requested > 0 && requested % 2 == 0 &&
              requested <= (agentUsesWiFi ? 4096u : 256u);
    }
    size_t offset = 0;
    for (char ch : offsetText) {
      if (ch < '0' || ch > '9' || offset > MAX_AUDIO_BYTES / 10) { valid = false; break; }
      offset = offset * 10 + ch - '0';
      if (offset > MAX_AUDIO_BYTES) { valid = false; break; }
    }
    if (!valid || !recordBuffer || offset >= recordSize || offset % 2) {
      protocolIO->println("BOX1 ERR recording_offset"); return;
    }
    recordActivity = millis();
    const size_t count = min(requested, recordSize - offset);
    const uint32_t checksum = esp_rom_crc32_le(0, recordBuffer + offset, count);
    if (!sendHex(recordBuffer + offset, count)) {
      protocolIO->println("\nBOX1 ERR usb_write"); return;
    }
    protocolIO->printf("BOX1 OK offset=%u bytes=%u crc=%08lx\n",
                  static_cast<unsigned>(offset), static_cast<unsigned>(count),
                  static_cast<unsigned long>(checksum));
  } else if (line.startsWith("BOX1 STREAM ")) {
    const String value = line.substring(12);
    char *end = nullptr;
    const unsigned long bytes = strtoul(value.c_str(), &end, 10);
    if (!speakerReady || !value.length() || *end || !bytes || bytes % 2 || bytes > 0x7ffffffeUL) {
      protocolIO->println("BOX1 ERR stream_size"); return;
    }
    cancelPlayback();
    releaseRecording();
    playBuffer = static_cast<uint8_t *>(ps_malloc(MAX_AUDIO_BYTES));
    if (!playBuffer) { protocolIO->println("BOX1 ERR memory"); return; }
    playExpected = bytes;
    playActivity = millis();
    streamWritten = streamRead = 0;
    streamStop = streamFailed = false;
    streamDone = false;
    streamUnderruns = streamStallMs = 0;
    streamPrefillBytes = agentUsesWiFi ? 16000 : 64000;
    streaming = true;
    lastStreamLength = 0;
    if (xTaskCreate(playbackStreamTask, "usb_audio", 4096, nullptr, 2, nullptr) != pdPASS) {
      streamDone = true;
      cancelPlayback();
      protocolIO->println("BOX1 ERR stream_task"); return;
    }
    protocolIO->printf("BOX1 OK stream=ring1 bytes=%u\n", static_cast<unsigned>(playExpected));
  } else if (line.startsWith("BOX1 PLAY ")) {
    size_t bytes;
    if (!speakerReady || !parseCount(line.substring(10), bytes)) {
      protocolIO->println("BOX1 ERR playback_unavailable_or_size"); return;
    }
    cancelPlayback();
    releaseRecording();
    playBuffer = static_cast<uint8_t *>(ps_malloc(bytes));
    if (!playBuffer) { protocolIO->println("BOX1 ERR memory"); return; }
    playExpected = bytes;
    playActivity = millis();
    protocolIO->println("BOX1 OK");
  } else if (line.startsWith("BOX1 CHUNK ")) {
    unsigned offset; unsigned long checksum; int prefix = 0;
    if (sscanf(line.c_str(), "BOX1 CHUNK %u %lx %n", &offset, &checksum, &prefix) != 2 || !prefix) {
      protocolIO->println("BOX1 ERR chunk_format"); return;
    }
    static uint8_t bytes[8192]; size_t length;
    if (!decodeHex(line.substring(prefix), bytes, sizeof(bytes), length) || !length || length % 2) {
      protocolIO->println("BOX1 ERR chunk_hex"); return;
    }
    if (esp_rom_crc32_le(0, bytes, length) != checksum) {
      protocolIO->println("BOX1 ERR chunk_crc"); return;
    }
    if (!playBuffer || offset > playExpected || length > playExpected - offset) {
      protocolIO->printf("BOX1 ERR chunk_buffer buffer=%d stream=%d offset=%u length=%u received=%u expected=%u\n",
                    playBuffer != nullptr, streaming, offset, static_cast<unsigned>(length),
                    static_cast<unsigned>(playReceived), static_cast<unsigned>(playExpected));
      return;
    }
    if (streaming) {
      if (streamFailed) { protocolIO->println("BOX1 ERR stream_playback"); return; }
      if (offset == playReceived) {
        // Backpressure must never block USB command handling.
        if (!streamDone && playReceived - streamRead.load() + length > MAX_AUDIO_BYTES) {
          protocolIO->printf("BOX1 ERR stream_busy next=%u read=%u\n", offset,
                        static_cast<unsigned>(streamRead.load()));
          return;
        }
        if (streamDone) { protocolIO->println("BOX1 ERR stream_stopped"); return; }
        for (size_t i = 0; i < length; ++i) playBuffer[(offset + i) % MAX_AUDIO_BYTES] = bytes[i];
        memcpy(lastStreamChunk, bytes, length);
        lastStreamOffset = offset;
        lastStreamLength = length;
        playReceived += length;
        streamWritten = playReceived;
      } else if (offset != lastStreamOffset || length != lastStreamLength ||
                 memcmp(bytes, lastStreamChunk, length)) {
        protocolIO->println("BOX1 ERR chunk_offset"); return;
      }
      playActivity = millis();
      protocolIO->printf("BOX1 OK next=%u\n", static_cast<unsigned>(offset + length));
      return;
    }
    // Repeating a committed block is safe; corrupted input never advances it.
    if (offset == playReceived) {
      memcpy(playBuffer + offset, bytes, length);
      playReceived += length;
    } else if (offset > playReceived || length > playReceived - offset ||
               memcmp(playBuffer + offset, bytes, length) != 0) {
      protocolIO->printf("BOX1 ERR chunk_offset next=%u\n", static_cast<unsigned>(playReceived)); return;
    }
    playActivity = millis();
    protocolIO->printf("BOX1 OK next=%u\n", static_cast<unsigned>(offset + length));
  } else if (line.startsWith("BOX1 DATA ")) {
    if (streaming) { protocolIO->println("BOX1 ERR stream_requires_chunk"); return; }
    uint8_t bytes[512]; size_t length;
    if (!playBuffer || !decodeHex(line.substring(10), bytes, sizeof(bytes), length) ||
        playReceived + length > playExpected) {
      protocolIO->printf("BOX1 ERR audio_payload buffer=%d hex_chars=%u received=%u expected=%u\n",
                    playBuffer != nullptr, static_cast<unsigned>(line.length() - 10),
                    static_cast<unsigned>(playReceived), static_cast<unsigned>(playExpected));
      cancelPlayback(); return;
    }
    memcpy(playBuffer + playReceived, bytes, length);
    playReceived += length;
    playActivity = millis();
    protocolIO->println("BOX1 OK");
  } else if (line == "BOX1 END") {
    if (!playBuffer || playReceived != playExpected) {
      cancelPlayback(); protocolIO->println("BOX1 ERR incomplete_audio"); return;
    }
    if (streaming) {
      while (!streamDone) delay(1);
      const bool ok = !streamFailed;
      cancelPlayback();
      if (ok) protocolIO->printf("BOX1 OK underruns=%lu stalled_ms=%lu\n",
                                 static_cast<unsigned long>(streamUnderruns.load()),
                                 static_cast<unsigned long>(streamStallMs.load()));
      else protocolIO->println("BOX1 ERR stream_playback");
      return;
    }
    boardSpeakerEnable(true);
    bool ok = true;
    for (size_t offset = 0; offset < playExpected && ok;) {
      int16_t stereo[512];
      const size_t count = min(static_cast<size_t>(256), (playExpected - offset) / 2);
      for (size_t i = 0; i < count; ++i) {
        const int16_t sample = static_cast<int16_t>(playBuffer[offset + i * 2] |
                                                   playBuffer[offset + i * 2 + 1] << 8);
        stereo[i * 2] = stereo[i * 2 + 1] = sample;
      }
      size_t sent = 0;
      ok = boardAudioWrite(stereo, count * 4, &sent, 200) == ESP_OK && sent == count * 4;
      offset += count * 2;
      delay(1);
    }
    delay(110); // Drain the six 240-frame DMA buffers before muting.
    cancelPlayback();
    protocolIO->println(ok ? "BOX1 OK" : "BOX1 ERR i2s_write");
  } else if (line.startsWith("BOX1 RECORD ")) {
    size_t bytes;
    if (!audioReady || !parseCount(line.substring(12), bytes)) {
      protocolIO->println("BOX1 ERR recording_unavailable_or_size"); return;
    }
    cancelPlayback();
    releaseRecording();
    uint8_t *recording = static_cast<uint8_t *>(ps_malloc(bytes));
    if (!recording) { protocolIO->println("BOX1 ERR memory"); return; }
    size_t captured = 0;
    esp_err_t captureError = ESP_OK;
    const uint32_t started = millis();
    while (captured < bytes && millis() - started < 12000) {
      int16_t stereo[512];
      const size_t frames = min(static_cast<size_t>(256), (bytes - captured) / 2);
      size_t received = 0;
      captureError = boardAudioRead(stereo, frames * 4, &received, 100);
      // IDF can return some valid data together with a timeout. Keep it and
      // retry rather than discarding all prior samples on a transient timeout.
      if (received % 4 || (captureError != ESP_OK && captureError != ESP_ERR_TIMEOUT)) break;
      for (size_t i = 0; i < received / 4; ++i) {
        const uint16_t sample = static_cast<uint16_t>(stereo[i * 2]);
        recording[captured++] = sample & 0xFF;
        recording[captured++] = sample >> 8;
      }
      updateVolumeMeter(stereo, received / sizeof(stereo[0]), 2, true);
      delay(1);
    }
    if (captured > 0) {
      recordBuffer = recording;
      recordSize = captured;
      recordActivity = millis();
      protocolIO->printf("BOX1 OK bytes=%u expected=%u partial=%d elapsed_ms=%lu error=%d audio=pull1\n",
                    static_cast<unsigned>(captured), static_cast<unsigned>(bytes), captured != bytes,
                    static_cast<unsigned long>(millis() - started), static_cast<int>(captureError));
    } else {
      free(recording);
      protocolIO->printf("BOX1 ERR i2s_read captured=0 expected=%u elapsed_ms=%lu error=%d\n",
                    static_cast<unsigned>(bytes), static_cast<unsigned long>(millis() - started),
                    static_cast<int>(captureError));
    }
  } else protocolIO->println("BOX1 ERR unknown_command");
}

void pollAgent() {
  static String line;
  static bool overflow = false;
  static uint32_t lastByte = 0;
  static bool tcpOwned = false;
  if (tcpOwned && !agentClient.connected()) {
    agentClient.stop();
    cancelPlayback();
    releaseRecording();
    line = "";
    overflow = false;
    tcpOwned = false;
    agentUsesWiFi = false;
    protocolIO = &Serial;
    // Discard USB commands queued while the network controller owned audio.
    while (Serial.available()) Serial.read();
  }
  if (!tcpOwned && agentServer.hasClient()) {
    // Do not hand an in-progress USB transaction to a network client.
    WiFiClient incoming = agentServer.accept();
    if (playBuffer || recordBuffer || line.length() ||
        millis() - usbCommandActivity < 1000) {
      incoming.println("BOX1 ERR controller_busy");
      incoming.stop();
    } else {
      agentClient = incoming;
      agentClient.setNoDelay(true);
      protocolIO = &agentClient;
      tcpOwned = true;
      agentUsesWiFi = true;
      requestedWiFi = true;
      line.reserve(16600);
      line = "";
      overflow = false;
    }
  }
  if (tcpOwned) {
    // Keep the native USB RX queue from replaying competing commands later.
    for (size_t n = 0; Serial.available() && n < 4096; ++n) Serial.read();
    if (agentServer.hasClient()) {
      WiFiClient extra = agentServer.accept();
      extra.println("BOX1 ERR controller_busy");
      extra.stop();
    }
  }
  if (line.length() && millis() - lastByte > 5000) {
    line = ""; overflow = false;
    protocolIO->println("BOX1 ERR command_timeout");
  }
  // The playback worker owns stream inactivity detection. Never silently free
  // an active ring: the next CHUNK must report a stream failure with context.
  if (playBuffer && !streaming && millis() - playActivity > 15000) cancelPlayback();
  if (recordBuffer && millis() - recordActivity > 30000) releaseRecording();
  // NetworkClient.available() queries the socket. Amortize that work across
  // a whole batch instead of repeating it for every byte of a hex audio frame.
  const size_t budget = agentUsesWiFi ? 17000u : 4096u;
  uint8_t incoming[512];
  size_t consumed = 0;
  while (consumed < budget) {
    const int available = protocolIO->available();
    if (available <= 0) break;
    const size_t count = min(min(size_t(available), sizeof(incoming)), budget - consumed);
    const int received = agentUsesWiFi ? agentClient.read(incoming, count) :
                                        Serial.read(incoming, count);
    if (received <= 0) break;
    consumed += received;
    lastByte = millis();
    for (int i = 0; i < received; ++i) {
      const char ch = incoming[i];
      if (ch == '\r') continue;
      if (ch == '\n') {
        if (overflow) protocolIO->println("BOX1 ERR line_too_long");
        else if (line.startsWith("BOX1 ")) {
          usbCommandActivity = millis();
          handleCommand(line);
          usbCommandActivity = millis();
        }
        line = ""; overflow = false;
      } else if (!overflow) {
        if (line.length() >= (agentUsesWiFi ? 16600u : 2200u)) overflow = true;
        else line += ch;
      }
    }
  }
}

#include "direct_cloud.h"

void setup() {
  // HWCDC drops bytes when its default 256-byte RX queue fills. A hex audio
  // command is over 1000 bytes; reserve room for the longest accepted line.
  Serial.setRxBufferSize(4096);
  Serial.begin(115200);
  if (!psramFound()) {
    Serial.println("Osiris requires PSRAM. Check the selected board and memory configuration.");
    while (true) delay(1000);
  }

  // 1. Initialize the display and backlight
  const bool displayReady = boardDisplayBegin();
  Serial.printf("LCD initialization: %s\n", displayReady ? "OK" : "FAILED");
  if (!displayReady) { while (true) delay(1000); }
  lcd.setBrightness(128);
  lcd.fillScreen(TFT_BLACK);
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  lcd.setCursor(10, 10);
  lcd.printf("%s starting...", BOARD_NAME);
  lcd.fillRect(20, 210, 90, 10, TFT_RED);
  lcd.fillRect(110, 210, 90, 10, TFT_GREEN);
  lcd.fillRect(200, 210, 90, 10, TFT_BLUE);
  Serial.println("LCD startup pattern drawn; initializing SD and audio.");

  // 2. Initialize the MicroSD card
  setupSD();

  // 3. Use bundled fonts so CJK text works without an SD font file.
  lcd.setFont(&fonts::Font0);

  // 4. Initialize the audio interface
  const bool i2sReady = setupI2S();
  audioReady = i2sReady && initCodec();
  speakerReady = i2sReady && initSpeaker();
  Serial.printf("Speaker initialization: %s\n", speakerReady ? "OK" : "FAILED");
  Serial.printf("Microphone initialization: %s\n", audioReady ? "OK" : "FAILED");

  // 5. Draw the initial screen
  lcd.fillScreen(TFT_BLACK);
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  lcd.setCursor(10, 10);
  lcd.printf("%s Ready", BOARD_NAME);

  lcd.setCursor(10, 30);
  lcd.print("Speak to test the microphone.");

  // Unicode escapes keep the source ASCII while rendering native text.
  printLocalizedText(10, 50, "Chinese (simplified): \u4E2D\u6587\u663E\u793A",
                     DisplayLanguage::SimplifiedChinese);
  printLocalizedText(10, 67, "Chinese (traditional): \u4E2D\u6587\u986F\u793A",
                     DisplayLanguage::TraditionalChinese);
  printLocalizedText(10, 84, "Japanese: \u65E5\u672C\u8A9E\u8868\u793A",
                     DisplayLanguage::Japanese);
  printLocalizedText(10, 101, "Korean: \uD55C\uAD6D\uC5B4 \uD45C\uC2DC",
                     DisplayLanguage::Korean);

  printLocalizedText(160, 10, "\U0001F916 \U0001F642 \U0001F3A4 \U0001F50A \u2705",
                     DisplayLanguage::English);

  // Draw the volume meter frame
  lcd.drawRect(20, 180, 280, 25, TFT_DARKGREY);
  setupWiFi();
  agentServer.begin();
  resetDirectCloud();
}

void loop() {
  pollSettings();
  if (subscriptionCredentialError.length()) {
    cloudScreen("error", subscriptionCredentialError);
    subscriptionCredentialError = "";
  }
  if (cloudSettingsChanged) {
    cloudSettingsChanged = false;
    agentClient.stop(); cancelPlayback(); releaseRecording();
    resetDirectCloud(); drawSettingsBar();
  }
  if (directCloudEnabled()) {
    // The standalone firmware owns the codecs; never accept host audio commands.
    if (agentServer.hasClient()) {
      WiFiClient extra = agentServer.accept();
      extra.println("BOX1 ERR standalone_mode"); extra.stop();
    }
    for (size_t n = 0; Serial.available() && n < 4096; ++n) Serial.read();
    pollDirectCloud(); delay(1); return;
  }
  pollAgent();
  // Prioritize the next stop-and-wait USB packet. A blocking idle microphone
  // read after every DATA/READ packet adds seconds before playback can start.
  if (playBuffer || (recordBuffer && millis() - recordActivity < 1000) ||
      millis() - usbCommandActivity < 10) {
    delay(1);
    return;
  }
  // 1. Handle touch input
  uint16_t x, y;
  if (!remoteDisplay && lcd.getTouch(&x, &y) && y < 212) {
    lcd.fillCircle(x, y, 4, TFT_GREEN);
    lcd.setCursor(10, 120);
    lcd.printf("Touch X=%d, Y=%d   ", x, y);
  }

  // Keep the idle meter on the same microphone channel used for recordings.
  if (audioReady) {
    int16_t samples[512];
    size_t bytes = 0;
    boardAudioRead(samples, sizeof(samples), &bytes, 50);
    updateVolumeMeter(samples, bytes / sizeof(samples[0]));
  } else {
    updateVolumeMeter(nullptr, 0);
    delay(10);
  }
}
