#define LGFX_USE_V1
#include <SD.h>
#include <atomic>
#include <LovyanGFX.hpp>
#include <Wire.h>
#include <ESP_I2S.h>
#include <SPI.h>
#include "utf8.h"
#include "serial_write.h"
#include "speech_gate.h"
#include <esp_rom_crc.h>
#include <driver/i2s_std.h>

constexpr int LCD_PIN_RESET = 48; // BOX-3 reset is active high, shared with touch.

// --- Hardware configuration: LovyanGFX display and touch ---
class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ILI9342  _panel_instance;
  lgfx::Bus_SPI       _bus_instance;
  lgfx::Light_PWM     _light_instance;
  lgfx::Touch_GT911   _touch_instance;

public:
  LGFX(void) {
    // Configure the SPI bus
    auto cfg = _bus_instance.config();
    cfg.spi_host = SPI2_HOST;
    cfg.spi_mode = 0;
    cfg.freq_write = 40000000;
    cfg.freq_read  = 16000000;
    cfg.spi_3wire  = true;
    cfg.pin_sclk = 7;
    cfg.pin_mosi = 6;
    cfg.pin_miso = -1;
    cfg.pin_dc   = 4;
    _bus_instance.config(cfg);
    _panel_instance.setBus(&_bus_instance);

    // Configure the LCD panel (320x240)
    auto p_cfg = _panel_instance.config();
    p_cfg.pin_cs   = 5;
    // Pulse the active-high reset in setup(); LGFX assumes active-low reset.
    p_cfg.pin_rst  = -1;
    p_cfg.pin_busy = -1;
    p_cfg.panel_width  = 320;
    p_cfg.panel_height = 240;
    p_cfg.offset_x = 0;
    p_cfg.offset_y = 0;
    p_cfg.invert   = false;
    p_cfg.readable = false; // The LCD has no MISO connection.
    p_cfg.rgb_order = false;
    _panel_instance.config(p_cfg);

    // Configure the backlight
    auto b_cfg = _light_instance.config();
    b_cfg.pin_bl = 47;
    b_cfg.invert = false;
    b_cfg.freq   = 44100;
    b_cfg.pwm_channel = 0;
    _light_instance.config(b_cfg);
    _panel_instance.setLight(&_light_instance);

    // Configure touch I2C
    auto t_cfg = _touch_instance.config();
    t_cfg.x_min = 0;
    t_cfg.x_max = 319;
    t_cfg.y_min = 0;
    t_cfg.y_max = 239;
    t_cfg.pin_int = 3;
    t_cfg.pin_rst = -1;
    t_cfg.bus_shared = false;
    t_cfg.i2c_port = I2C_NUM_0;
    t_cfg.pin_sda = 8;
    t_cfg.pin_scl = 18;
    t_cfg.freq = 400000;
    _touch_instance.config(t_cfg);
    _panel_instance.setTouch(&_touch_instance);

    setPanel(&_panel_instance);
  }
};

LGFX lcd;

// Compact color emoji artwork for common agent and audio status messages.
// Unsupported supplementary-plane symbols use a visible placeholder.
bool drawEmoji(uint32_t codepoint, int x, int y) {
  switch (codepoint) {
    case 0x1F600: // Grinning face
    case 0x1F642: // Slightly smiling face
    case 0x1F914: // Thinking face
      lcd.fillCircle(x + 8, y + 8, 7, TFT_YELLOW);
      lcd.fillCircle(x + 5, y + 6, 1, TFT_BLACK);
      lcd.fillCircle(x + 11, y + 6, 1, TFT_BLACK);
      if (codepoint == 0x1F914) {
        lcd.drawLine(x + 5, y + 11, x + 10, y + 10, TFT_BLACK);
        lcd.fillCircle(x + 12, y + 13, 2, TFT_ORANGE);
      } else {
        lcd.drawLine(x + 4, y + 10, x + 6, y + 12, TFT_BLACK);
        lcd.drawLine(x + 6, y + 12, x + 10, y + 12, TFT_BLACK);
        lcd.drawLine(x + 10, y + 12, x + 12, y + 10, TFT_BLACK);
      }
      return true;
    case 0x1F916: // Robot
      lcd.fillRoundRect(x + 1, y + 3, 14, 12, 2, TFT_LIGHTGREY);
      lcd.drawLine(x + 8, y, x + 8, y + 3, TFT_WHITE);
      lcd.fillRect(x + 4, y + 6, 2, 3, TFT_BLUE);
      lcd.fillRect(x + 10, y + 6, 2, 3, TFT_BLUE);
      lcd.drawLine(x + 5, y + 12, x + 11, y + 12, TFT_BLACK);
      return true;
    case 0x1F3A4: // Microphone
      lcd.fillRoundRect(x + 5, y + 1, 6, 9, 3, TFT_LIGHTGREY);
      lcd.drawLine(x + 3, y + 8, x + 5, y + 12, TFT_WHITE);
      lcd.drawLine(x + 5, y + 12, x + 11, y + 12, TFT_WHITE);
      lcd.drawLine(x + 11, y + 12, x + 13, y + 8, TFT_WHITE);
      lcd.drawLine(x + 8, y + 12, x + 8, y + 15, TFT_WHITE);
      return true;
    case 0x1F50A: // Speaker
      lcd.fillRect(x + 1, y + 6, 4, 5, TFT_WHITE);
      lcd.fillTriangle(x + 4, y + 6, x + 9, y + 2, x + 9, y + 14, TFT_WHITE);
      lcd.drawLine(x + 12, y + 5, x + 14, y + 8, TFT_CYAN);
      lcd.drawLine(x + 14, y + 8, x + 12, y + 11, TFT_CYAN);
      return true;
    case 0x2705: // Check mark
      lcd.fillRoundRect(x, y, 16, 16, 2, TFT_DARKGREEN);
      lcd.drawLine(x + 3, y + 8, x + 6, y + 12, TFT_WHITE);
      lcd.drawLine(x + 6, y + 12, x + 13, y + 4, TFT_WHITE);
      return true;
    case 0x274C: // Cross mark
      lcd.drawLine(x + 3, y + 3, x + 13, y + 13, TFT_RED);
      lcd.drawLine(x + 13, y + 3, x + 3, y + 13, TFT_RED);
      return true;
    case 0x26A0: // Warning
      lcd.fillTriangle(x + 8, y, x, y + 15, x + 15, y + 15, TFT_YELLOW);
      lcd.fillRect(x + 7, y + 5, 2, 5, TFT_BLACK);
      lcd.fillRect(x + 7, y + 12, 2, 2, TFT_BLACK);
      return true;
    case 0x2764: // Heart
      lcd.fillCircle(x + 4, y + 5, 4, TFT_RED);
      lcd.fillCircle(x + 11, y + 5, 4, TFT_RED);
      lcd.fillTriangle(x, y + 6, x + 15, y + 6, x + 8, y + 15, TFT_RED);
      return true;
    default: return false;
  }
}

// Large status avatar stays beside the conversation; inline emoji remain small.
String agentExpression = "happy";
void drawAgentFace() {
  lcd.fillRect(0, 0, 100, 140, TFT_BLACK);
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  lcd.setCursor(12, 4);
  lcd.print("Pi Agent");
  const bool error = agentExpression == "error";
  const bool thinking = agentExpression == "thinking";
  const bool speaking = agentExpression == "speaking";
  const bool music = agentExpression == "music";
  const bool sad = agentExpression == "sad";
  const uint16_t color = error ? TFT_RED : thinking ? TFT_YELLOW : TFT_CYAN;
  lcd.fillRoundRect(8, 32, 84, 70, 15, color);
  lcd.drawLine(50, 20, 50, 31, color);
  lcd.fillCircle(50, 19, 4, color);
  lcd.fillRoundRect(16, 40, 68, 48, 10, TFT_BLACK);
  if (music || agentExpression == "happy") {
    lcd.drawLine(26, 57, 32, 51, color);
    lcd.drawLine(32, 51, 38, 57, color);
    lcd.drawLine(62, 57, 68, 51, color);
    lcd.drawLine(68, 51, 74, 57, color);
  } else if (error) {
    for (int x : {26, 62}) {
      lcd.drawLine(x, 49, x + 12, 61, color);
      lcd.drawLine(x + 12, 49, x, 61, color);
    }
  } else {
    lcd.fillRoundRect(27, thinking ? 52 : 48, 10, thinking ? 4 : 15, 3, color);
    lcd.fillRoundRect(63, 48, 10, 15, 3, color);
  }
  if (speaking || music) lcd.fillRoundRect(39, 68, 22, 13, 6, color);
  else if (sad || error) {
    lcd.drawLine(37, 79, 44, 73, color);
    lcd.drawLine(44, 73, 56, 73, color);
    lcd.drawLine(56, 73, 63, 79, color);
  } else if (thinking) lcd.fillRect(40, 74, 20, 3, color);
  else {
    lcd.drawLine(36, 70, 43, 77, color);
    lcd.drawLine(43, 77, 57, 77, color);
    lcd.drawLine(57, 77, 64, 70, color);
  }
  lcd.setCursor(10, 112);
  lcd.print(agentExpression);
  lcd.drawFastVLine(100, 0, 140, TFT_DARKGREY);
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
    const bool emoji = codepoint >= 0x1F000 || codepoint == 0x2705 ||
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

// BOX-3 SD slot: use SPI3 (HSPI); the LCD owns SPI2.
constexpr int SD_PIN_SCLK = 11;
constexpr int SD_PIN_MISO = 9;
constexpr int SD_PIN_MOSI = 14;
constexpr int SD_PIN_CS = 12;
constexpr int SD_PIN_POWER = 43; // Active low.
SPIClass sdSPI(HSPI);

bool setupSD() {
  pinMode(SD_PIN_POWER, OUTPUT);
  digitalWrite(SD_PIN_POWER, LOW);
  delay(100);
  pinMode(SD_PIN_CS, OUTPUT);
  digitalWrite(SD_PIN_CS, HIGH);
  sdSPI.begin(SD_PIN_SCLK, SD_PIN_MISO, SD_PIN_MOSI, SD_PIN_CS);
  if (!SD.begin(SD_PIN_CS, sdSPI, 1000000)) {
    Serial.println("SD mount failed on BOX-3 pins; check card seating and filesystem.");
    return false;
  }
  Serial.printf("SD mounted: %llu MB\n", SD.cardSize() / (1024ULL * 1024ULL));
  return true;
}

// --- Audio hardware configuration: ES7210 and I2S ---
#define I2C_SDA 8
#define I2C_SCL 18
#define ES7210_ADDR 0x40

I2SClass i2s;
bool audioReady = false;
bool speakerReady = false;
bool remoteDisplay = false;
#define I2S_PIN_MCLK 2
#define I2S_PIN_SCLK 17
#define I2S_PIN_LRCK 45
#define I2S_PIN_DIN  16

bool initCodec() {
  // Share LovyanGFX's I2C implementation with touch instead of installing
  // a second driver on the same controller. ES7210: 16 kHz, MCLK = 256 * Fs,
  // Standard 16-bit stereo data in 32-bit slots (64 BCLK per frame).
  // Complete startup sequence from Espressif's BSP codec driver:
  // https://github.com/espressif/esp-bsp/blob/master/components/es7210/es7210.c
  if (!lgfx::i2c::init(I2C_NUM_0, I2C_SDA, I2C_SCL).has_value()) return false;
  const uint8_t settings[][2] = {
    {0x00, 0xFF}, {0x00, 0x32},
    {0x09, 0x30}, {0x0A, 0x30},
    {0x23, 0x2A}, {0x22, 0x0A}, {0x20, 0x0A}, {0x21, 0x2A},
    {0x08, 0x10}, {0x40, 0xC3}, {0x41, 0x70}, {0x42, 0x70},
    {0x07, 0x20}, {0x02, 0xC1}, {0x04, 0x01}, {0x05, 0x00},
    {0x11, 0x60}, {0x12, 0x00},
    {0x43, 0x18}, {0x44, 0x18}, {0x45, 0x18}, {0x46, 0x18},
    {0x47, 0x08}, {0x48, 0x08}, {0x49, 0x08}, {0x4A, 0x08},
    {0x4B, 0x0F}, {0x4C, 0x0F}, {0x06, 0x04}, {0x01, 0x20},
    {0x00, 0x71}, {0x00, 0x41}
  };
  for (const auto &setting : settings) {
    if (!lgfx::i2c::transactionWrite(I2C_NUM_0, ES7210_ADDR,
                                    setting, sizeof(setting), 400000).has_value()) {
      Serial.printf("ES7210 write failed: register 0x%02X, address 0x%02X\n",
                    setting[0], ES7210_ADDR);
      return false;
    }
  }
  delay(100);
  // Acknowledged writes alone do not prove that reset/configuration took effect.
  const uint8_t expected[][2] = {
    {0x00, 0x41}, {0x01, 0x20}, {0x02, 0xC1}, {0x08, 0x10},
    {0x11, 0x60}, {0x12, 0x00}
  };
  for (const auto &entry : expected) {
    uint8_t value = 0;
    if (!lgfx::i2c::transactionWriteRead(I2C_NUM_0, ES7210_ADDR, entry, 1,
                                        &value, 1, 400000).has_value() || value != entry[1]) {
      Serial.printf("ES7210 verification failed: reg=%02X expected=%02X actual=%02X\n",
                    entry[0], entry[1], value);
      return false;
    }
  }
  return true;
}

bool setupI2S() {
  i2s.setTimeout(50);
  i2s.setPins(I2S_PIN_SCLK, I2S_PIN_LRCK, 15, I2S_PIN_DIN, I2S_PIN_MCLK);
  if (!i2s.begin(I2S_MODE_STD, 16000, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("Failed to initialize I2S!");
    return false;
  }
  // Keep PCM buffers 16-bit, but provide a full 32-clock slot for each codec
  // channel. Apply identical timing to TX/RX because they share BCLK and WS.
  i2s_std_slot_config_t slots = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  slots.slot_bit_width = I2S_SLOT_BIT_WIDTH_32BIT;
  slots.ws_width = 32;
  // Recalculate BCLK after widening the slots; retaining the old divider can
  // halve WS/sample rate while the WAV still declares 16000 Hz.
  i2s_std_clk_config_t clocks = I2S_STD_CLK_DEFAULT_CONFIG(16000);
  clocks.mclk_multiple = I2S_MCLK_MULTIPLE_256;
  if (i2s_channel_disable(i2s.txChan()) != ESP_OK ||
      i2s_channel_disable(i2s.rxChan()) != ESP_OK ||
      i2s_channel_reconfig_std_slot(i2s.txChan(), &slots) != ESP_OK ||
      i2s_channel_reconfig_std_slot(i2s.rxChan(), &slots) != ESP_OK ||
      i2s_channel_reconfig_std_clock(i2s.txChan(), &clocks) != ESP_OK ||
      i2s_channel_reconfig_std_clock(i2s.rxChan(), &clocks) != ESP_OK ||
      i2s_channel_enable(i2s.txChan()) != ESP_OK ||
      i2s_channel_enable(i2s.rxChan()) != ESP_OK) {
    Serial.println("Failed to configure 32-bit I2S slots!");
    i2s.end();
    return false;
  }
  return true;
}

// ES8311 DAC: 16 kHz, 256x MCLK, standard 16-bit I2S; amplifier GPIO46.
// Clock and power configuration follows the ESPHome ES8311 implementation.
bool initSpeaker() {
  pinMode(46, OUTPUT);
  digitalWrite(46, LOW);
  const uint8_t settings[][2] = {
    {0x00, 0x1F}, {0x00, 0x00}, {0x01, 0x3F}, {0x02, 0x00},
    {0x03, 0x10}, {0x04, 0x20}, {0x05, 0x00}, {0x06, 0x03},
    {0x07, 0x00}, {0x08, 0xFF}, {0x09, 0x0C}, {0x0A, 0x0C},
    {0x14, 0x1A}, {0x16, 0x00}, {0x17, 0xC8}, {0x32, 0xBF}, // DAC unity gain.
    {0x0D, 0x01}, {0x0E, 0x02}, {0x12, 0x00}, {0x13, 0x10},
    {0x1C, 0x6A}, {0x37, 0x08}, {0x31, 0x00}, {0x00, 0x80}
  };
  for (const auto &setting : settings) {
    if (!lgfx::i2c::transactionWrite(I2C_NUM_0, 0x18, setting, 2, 400000).has_value()) {
      return false;
    }
  }
  return true;
}

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
uint8_t lastStreamChunk[256];
size_t lastStreamOffset = 0, lastStreamLength = 0;

void playbackStreamTask(void *) {
  uint32_t lastData = millis();
  size_t previousWritten = 0;
  // Prefill two seconds; timeout measures inactivity, not total upload time.
  while (!streamStop && streamWritten < min(playExpected, size_t(64000))) {
    const size_t written = streamWritten.load();
    if (written != previousWritten) { lastData = millis(); previousWritten = written; }
    if (millis() - lastData > STREAM_IDLE_MS) { streamFailed = true; break; }
    delay(1);
  }
  if (!streamStop && !streamFailed) digitalWrite(46, HIGH);
  while (!streamStop && !streamFailed && streamRead < playExpected) {
    const size_t offset = streamRead.load();
    const size_t available = streamWritten.load() - offset;
    if (!available) {
      if (millis() - lastData > STREAM_IDLE_MS) streamFailed = true;
      delay(1);
      continue;
    }
    int16_t stereo[512];
    const size_t count = min(size_t(256), available / 2);
    for (size_t i = 0; i < count; ++i) {
      const size_t pos = (offset + i * 2) % MAX_AUDIO_BYTES;
      const int16_t sample = int16_t(playBuffer[pos] | (playBuffer[pos + 1] << 8));
      stereo[i * 2] = stereo[i * 2 + 1] = sample;
    }
    size_t sent = 0;
    const esp_err_t writeError = i2s_channel_write(i2s.txChan(), stereo, count * 4, &sent, 200);
    if (writeError != ESP_OK || sent != count * 4) {
      streamFailed = true;
      break;
    }
    streamRead = offset + count * 2;
    lastData = millis();
  }
  delay(110);
  digitalWrite(46, LOW);
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
  digitalWrite(46, LOW);
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

bool sendHex(const uint8_t *bytes, size_t size) {
  static const char digits[] = "0123456789abcdef";
  // Keep each line below the default USB CDC TX ring-buffer size.
  char line[139];
  while (size) {
    const size_t count = size > 64 ? 64 : size;
    memcpy(line, "BOX1 DATA ", 10);
    for (size_t i = 0; i < count; ++i) {
      line[10 + i * 2] = digits[bytes[i] >> 4];
      line[11 + i * 2] = digits[bytes[i] & 15];
    }
    line[10 + count * 2] = '\n';
    if (!writeFully(Serial, reinterpret_cast<uint8_t *>(line), 11 + count * 2)) {
      return false;
    }
    bytes += count;
    size -= count;
    delay(1);
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
  if (!audio) { Serial.println("BOX1 ERR memory"); return; }
  // Keep 256 ms before onset so the first syllable is preserved.
  int16_t *preroll = static_cast<int16_t *>(ps_malloc(4096 * sizeof(int16_t)));
  if (!preroll) { free(audio); Serial.println("BOX1 ERR memory"); return; }
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
    error = i2s_channel_read(i2s.rxChan(), stereo, sizeof(stereo), &received, 100);
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
      Serial.println("BOX1 EVENT speech_start");
    }
    updateVolumeMeter(stereo, received / 2, 2, gate.started);
    if (gate.finished) break;
    delay(1);
  }
  free(preroll);
  if (!gate.started && (error == ESP_OK || error == ESP_ERR_TIMEOUT)) {
    free(audio);
    Serial.println("BOX1 OK bytes=0 audio=pull1 reason=silence");
  } else if (!gate.started || (!gate.finished && captured < MAX_AUDIO_BYTES)) {
    free(audio);
    Serial.printf("BOX1 ERR listen_read error=%d\n", static_cast<int>(error));
  } else {
    recordBuffer = audio;
    recordSize = captured;
    recordActivity = millis();
    Serial.printf("BOX1 OK bytes=%u audio=pull1 reason=%s\n",
                  static_cast<unsigned>(captured), gate.finished ? "silence" : "limit");
  }
}

void handleCommand(const String &line) {
  if (line == "BOX1 PING") {
    Serial.printf("BOX1 OK mic=%d speaker=%d rate=16000 audio=pull1 capture=slot32-v3 playback=usbfast-v2 rx=4096 vad=1 upload=checked1 stream=ring1 streamrev=4 sync=1 face=1\n", audioReady, speakerReady);
  } else if (line.startsWith("BOX1 LISTEN ")) {
    int threshold; unsigned silenceMs, waitMs; char extra;
    if (!audioReady || sscanf(line.c_str(), "BOX1 LISTEN %d %u %u %c",
                              &threshold, &silenceMs, &waitMs, &extra) != 3 ||
        threshold < 1 || threshold > 32768 || silenceMs < 250 || silenceMs > 5000 ||
        waitMs < 250 || waitMs > 10000) {
      Serial.println("BOX1 ERR listen_parameters"); return;
    }
    listenForSpeech(threshold, silenceMs, waitMs);
  } else if (line.startsWith("BOX1 FACE ")) {
    const String expression = line.substring(10);
    if (expression != "happy" && expression != "sad" && expression != "listening" &&
        expression != "thinking" && expression != "speaking" && expression != "music" && expression != "error") {
      Serial.println("BOX1 ERR expression"); return;
    }
    agentExpression = expression;
    drawAgentFace();
    Serial.println("BOX1 OK");
  } else if (line.startsWith("BOX1 TEXT ")) {
    const int split = line.indexOf(' ', 10);
    if (split < 0) { Serial.println("BOX1 ERR text_format"); return; }
    const String language = line.substring(10, split);
    DisplayLanguage selected;
    if (language == "en") selected = DisplayLanguage::English;
    else if (language == "zh") selected = DisplayLanguage::SimplifiedChinese;
    else if (language == "zh-TW") selected = DisplayLanguage::TraditionalChinese;
    else if (language == "ja") selected = DisplayLanguage::Japanese;
    else if (language == "ko") selected = DisplayLanguage::Korean;
    else { Serial.println("BOX1 ERR language"); return; }
    char text[1025];
    size_t length;
    if (!decodeHex(line.substring(split + 1), reinterpret_cast<uint8_t *>(text), 1024, length)) {
      Serial.println("BOX1 ERR text_hex"); return;
    }
    text[length] = 0;
    remoteDisplay = true;
    drawAgentFace();
    lcd.fillRect(104, 0, 216, 140, TFT_BLACK);
    lcd.setClipRect(104, 0, 216, 140);
    printLocalizedText(104, 4, text, selected);
    lcd.clearClipRect();
    Serial.println("BOX1 OK");
  } else if (line.startsWith("BOX1 SYNC ")) {
    const String token = line.substring(10);
    if (!token.length() || token.length() > 32) { Serial.println("BOX1 ERR sync_token"); return; }
    Serial.printf("\nBOX1 OK sync=%s next=%u read=%u failed=%d done=%d\n", token.c_str(),
                  static_cast<unsigned>(playReceived), static_cast<unsigned>(streamRead.load()),
                  streamFailed.load(), streamDone.load());
  } else if (line.startsWith("BOX1 RESET ")) {
    const String token = line.substring(11);
    if (!token.length() || token.length() > 32) { Serial.println("BOX1 ERR reset_token"); return; }
    cancelPlayback(); releaseRecording();
    Serial.printf("BOX1 OK sync=%s\n", token.c_str());
  } else if (line == "BOX1 CANCEL") {
    cancelPlayback(); releaseRecording(); Serial.println("BOX1 OK");
  } else if (line.startsWith("BOX1 READ ")) {
    const String value = line.substring(10);
    size_t offset = 0;
    bool valid = value.length() > 0;
    for (char ch : value) {
      if (ch < '0' || ch > '9' || offset > MAX_AUDIO_BYTES / 10) { valid = false; break; }
      offset = offset * 10 + ch - '0';
      if (offset > MAX_AUDIO_BYTES) { valid = false; break; }
    }
    if (!valid || !recordBuffer || offset >= recordSize || offset % 2) {
      Serial.println("BOX1 ERR recording_offset"); return;
    }
    recordActivity = millis();
    const size_t count = min(static_cast<size_t>(256), recordSize - offset);
    const uint32_t checksum = esp_rom_crc32_le(0, recordBuffer + offset, count);
    if (!sendHex(recordBuffer + offset, count)) {
      Serial.println("\nBOX1 ERR usb_write"); return;
    }
    Serial.printf("BOX1 OK offset=%u bytes=%u crc=%08lx\n",
                  static_cast<unsigned>(offset), static_cast<unsigned>(count),
                  static_cast<unsigned long>(checksum));
  } else if (line.startsWith("BOX1 STREAM ")) {
    const String value = line.substring(12);
    char *end = nullptr;
    const unsigned long bytes = strtoul(value.c_str(), &end, 10);
    if (!speakerReady || !value.length() || *end || !bytes || bytes % 2 || bytes > 0x7ffffffeUL) {
      Serial.println("BOX1 ERR stream_size"); return;
    }
    cancelPlayback();
    releaseRecording();
    playBuffer = static_cast<uint8_t *>(ps_malloc(MAX_AUDIO_BYTES));
    if (!playBuffer) { Serial.println("BOX1 ERR memory"); return; }
    playExpected = bytes;
    playActivity = millis();
    streamWritten = streamRead = 0;
    streamStop = streamFailed = false;
    streamDone = false;
    streaming = true;
    lastStreamLength = 0;
    if (xTaskCreate(playbackStreamTask, "usb_audio", 4096, nullptr, 2, nullptr) != pdPASS) {
      streamDone = true;
      cancelPlayback();
      Serial.println("BOX1 ERR stream_task"); return;
    }
    Serial.printf("BOX1 OK stream=ring1 bytes=%u\n", static_cast<unsigned>(playExpected));
  } else if (line.startsWith("BOX1 PLAY ")) {
    size_t bytes;
    if (!speakerReady || !parseCount(line.substring(10), bytes)) {
      Serial.println("BOX1 ERR playback_unavailable_or_size"); return;
    }
    cancelPlayback();
    releaseRecording();
    playBuffer = static_cast<uint8_t *>(ps_malloc(bytes));
    if (!playBuffer) { Serial.println("BOX1 ERR memory"); return; }
    playExpected = bytes;
    playActivity = millis();
    Serial.println("BOX1 OK");
  } else if (line.startsWith("BOX1 CHUNK ")) {
    unsigned offset; unsigned long checksum; int prefix = 0;
    if (sscanf(line.c_str(), "BOX1 CHUNK %u %lx %n", &offset, &checksum, &prefix) != 2 || !prefix) {
      Serial.println("BOX1 ERR chunk_format"); return;
    }
    uint8_t bytes[256]; size_t length;
    if (!decodeHex(line.substring(prefix), bytes, sizeof(bytes), length) || !length || length % 2) {
      Serial.println("BOX1 ERR chunk_hex"); return;
    }
    if (esp_rom_crc32_le(0, bytes, length) != checksum) {
      Serial.println("BOX1 ERR chunk_crc"); return;
    }
    if (!playBuffer || offset > playExpected || length > playExpected - offset) {
      Serial.printf("BOX1 ERR chunk_buffer buffer=%d stream=%d offset=%u length=%u received=%u expected=%u\n",
                    playBuffer != nullptr, streaming, offset, static_cast<unsigned>(length),
                    static_cast<unsigned>(playReceived), static_cast<unsigned>(playExpected));
      return;
    }
    if (streaming) {
      if (streamFailed) { Serial.println("BOX1 ERR stream_playback"); return; }
      if (offset == playReceived) {
        // Backpressure must never block USB command handling.
        if (!streamDone && playReceived - streamRead.load() + length > MAX_AUDIO_BYTES) {
          Serial.printf("BOX1 ERR stream_busy next=%u read=%u\n", offset,
                        static_cast<unsigned>(streamRead.load()));
          return;
        }
        if (streamDone) { Serial.println("BOX1 ERR stream_stopped"); return; }
        for (size_t i = 0; i < length; ++i) playBuffer[(offset + i) % MAX_AUDIO_BYTES] = bytes[i];
        memcpy(lastStreamChunk, bytes, length);
        lastStreamOffset = offset;
        lastStreamLength = length;
        playReceived += length;
        streamWritten = playReceived;
      } else if (offset != lastStreamOffset || length != lastStreamLength ||
                 memcmp(bytes, lastStreamChunk, length)) {
        Serial.println("BOX1 ERR chunk_offset"); return;
      }
      playActivity = millis();
      Serial.printf("BOX1 OK next=%u\n", static_cast<unsigned>(offset + length));
      return;
    }
    // Repeating a committed block is safe; corrupted input never advances it.
    if (offset == playReceived) {
      memcpy(playBuffer + offset, bytes, length);
      playReceived += length;
    } else if (offset > playReceived || length > playReceived - offset ||
               memcmp(playBuffer + offset, bytes, length) != 0) {
      Serial.printf("BOX1 ERR chunk_offset next=%u\n", static_cast<unsigned>(playReceived)); return;
    }
    playActivity = millis();
    Serial.printf("BOX1 OK next=%u\n", static_cast<unsigned>(offset + length));
  } else if (line.startsWith("BOX1 DATA ")) {
    if (streaming) { Serial.println("BOX1 ERR stream_requires_chunk"); return; }
    uint8_t bytes[512]; size_t length;
    if (!playBuffer || !decodeHex(line.substring(10), bytes, sizeof(bytes), length) ||
        playReceived + length > playExpected) {
      Serial.printf("BOX1 ERR audio_payload buffer=%d hex_chars=%u received=%u expected=%u\n",
                    playBuffer != nullptr, static_cast<unsigned>(line.length() - 10),
                    static_cast<unsigned>(playReceived), static_cast<unsigned>(playExpected));
      cancelPlayback(); return;
    }
    memcpy(playBuffer + playReceived, bytes, length);
    playReceived += length;
    playActivity = millis();
    Serial.println("BOX1 OK");
  } else if (line == "BOX1 END") {
    if (!playBuffer || playReceived != playExpected) {
      cancelPlayback(); Serial.println("BOX1 ERR incomplete_audio"); return;
    }
    if (streaming) {
      while (!streamDone) delay(1);
      const bool ok = !streamFailed;
      cancelPlayback();
      Serial.println(ok ? "BOX1 OK" : "BOX1 ERR stream_playback");
      return;
    }
    digitalWrite(46, HIGH);
    bool ok = true;
    for (size_t offset = 0; offset < playExpected && ok;) {
      int16_t stereo[512];
      const size_t count = min(static_cast<size_t>(256), (playExpected - offset) / 2);
      for (size_t i = 0; i < count; ++i) {
        const int16_t sample = static_cast<int16_t>(playBuffer[offset + i * 2] |
                                                   playBuffer[offset + i * 2 + 1] << 8);
        stereo[i * 2] = stereo[i * 2 + 1] = sample;
      }
      ok = i2s.write(reinterpret_cast<uint8_t *>(stereo), count * 4) == count * 4;
      offset += count * 2;
      delay(1);
    }
    delay(110); // Drain the six 240-frame DMA buffers before muting.
    cancelPlayback();
    Serial.println(ok ? "BOX1 OK" : "BOX1 ERR i2s_write");
  } else if (line.startsWith("BOX1 RECORD ")) {
    size_t bytes;
    if (!audioReady || !parseCount(line.substring(12), bytes)) {
      Serial.println("BOX1 ERR recording_unavailable_or_size"); return;
    }
    cancelPlayback();
    releaseRecording();
    uint8_t *recording = static_cast<uint8_t *>(ps_malloc(bytes));
    if (!recording) { Serial.println("BOX1 ERR memory"); return; }
    size_t captured = 0;
    esp_err_t captureError = ESP_OK;
    const uint32_t started = millis();
    while (captured < bytes && millis() - started < 12000) {
      int16_t stereo[512];
      const size_t frames = min(static_cast<size_t>(256), (bytes - captured) / 2);
      size_t received = 0;
      captureError = i2s_channel_read(i2s.rxChan(), stereo, frames * 4, &received, 100);
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
      Serial.printf("BOX1 OK bytes=%u expected=%u partial=%d elapsed_ms=%lu error=%d audio=pull1\n",
                    static_cast<unsigned>(captured), static_cast<unsigned>(bytes), captured != bytes,
                    static_cast<unsigned long>(millis() - started), static_cast<int>(captureError));
    } else {
      free(recording);
      Serial.printf("BOX1 ERR i2s_read captured=0 expected=%u elapsed_ms=%lu error=%d\n",
                    static_cast<unsigned>(bytes), static_cast<unsigned long>(millis() - started),
                    static_cast<int>(captureError));
    }
  } else Serial.println("BOX1 ERR unknown_command");
}

void pollUSB() {
  static String line;
  static bool overflow = false;
  static uint32_t lastByte = 0;
  if (line.length() && millis() - lastByte > 5000) {
    line = ""; overflow = false;
    Serial.println("BOX1 ERR command_timeout");
  }
  // The playback worker owns stream inactivity detection. Never silently free
  // an active ring: the next CHUNK must report a stream failure with context.
  if (playBuffer && !streaming && millis() - playActivity > 15000) cancelPlayback();
  if (recordBuffer && millis() - recordActivity > 30000) releaseRecording();
  for (size_t budget = 0; Serial.available() && budget < 4096; ++budget) {
    const char ch = Serial.read();
    lastByte = millis();
    if (ch == '\r') continue;
    if (ch == '\n') {
      if (overflow) Serial.println("BOX1 ERR line_too_long");
      else if (line.startsWith("BOX1 ")) {
        usbCommandActivity = millis();
        handleCommand(line);
        usbCommandActivity = millis();
      }
      line = ""; overflow = false;
    } else if (!overflow) {
      if (line.length() >= 2200) overflow = true;
      else line += ch;
    }
  }
}

void setup() {
  // HWCDC drops bytes when its default 256-byte RX queue fills. A hex audio
  // command is over 1000 bytes; reserve room for the longest accepted line.
  Serial.setRxBufferSize(4096);
  Serial.begin(115200);

  // 1. Initialize the display and backlight
  pinMode(LCD_PIN_RESET, OUTPUT);
  digitalWrite(LCD_PIN_RESET, HIGH);
  delay(20);
  digitalWrite(LCD_PIN_RESET, LOW);
  delay(120);
  const bool displayReady = lcd.init();
  lcd.setRotation(2); // Rotate 180 degrees for the BOX-3 mounting orientation.
  Serial.printf("LCD initialization: %s\n", displayReady ? "OK" : "FAILED");
  lcd.setBrightness(128);
  lcd.fillScreen(TFT_BLACK);
  lcd.setTextColor(TFT_WHITE, TFT_BLACK);
  lcd.setCursor(10, 10);
  lcd.print("ESP32-S3-BOX-3 starting...");
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
  lcd.print("ESP32-S3-BOX-3 Ready");

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
}

void loop() {
  pollUSB();
  // Prioritize the next stop-and-wait USB packet. A blocking idle microphone
  // read after every DATA/READ packet adds seconds before playback can start.
  if (playBuffer || (recordBuffer && millis() - recordActivity < 1000) ||
      millis() - usbCommandActivity < 10) {
    delay(1);
    return;
  }
  // 1. Handle touch input
  uint16_t x, y;
  if (!remoteDisplay && lcd.getTouch(&x, &y)) {
    lcd.fillCircle(x, y, 4, TFT_GREEN);
    lcd.setCursor(10, 120);
    lcd.printf("Touch X=%d, Y=%d   ", x, y);
  }

  // Keep the idle meter on the same microphone channel used for recordings.
  if (audioReady) {
    int16_t samples[512];
    const size_t bytes = i2s.readBytes(reinterpret_cast<char *>(samples), sizeof(samples));
    updateVolumeMeter(samples, bytes / sizeof(samples[0]));
  } else {
    updateVolumeMeter(nullptr, 0);
    delay(10);
  }
}
