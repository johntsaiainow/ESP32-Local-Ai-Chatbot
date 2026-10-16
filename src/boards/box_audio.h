#pragma once
// BOX-3 SD slot: use SPI3 (HSPI); the LCD owns SPI2.
constexpr int SD_PIN_SCLK = 11;
constexpr int SD_PIN_MISO = 9;
constexpr int SD_PIN_MOSI = 14;
constexpr int SD_PIN_CS = 12;
constexpr int SD_PIN_POWER = 43; // Active low.
SPIClass sdSPI(HSPI);

bool setupSD() {
#if defined(OSIRIS_LICHUANG_S3)
  return false; // Do not drive BOX-3 SD pins on another PCB.
#else
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
#endif
}

// --- Audio hardware configuration: ES7210 and I2S ---
#if defined(OSIRIS_LICHUANG_S3)
#define I2C_SDA 1
#define I2C_SCL 2
#define ES7210_ADDR 0x41 // Upstream uses the 8-bit address 0x82.
#define I2S_PIN_MCLK 38
#define I2S_PIN_SCLK 14
#define I2S_PIN_LRCK 13
#define I2S_PIN_DIN 12
#define I2S_PIN_DOUT 45
#else
#define I2C_SDA 8
#define I2C_SCL 18
#define ES7210_ADDR 0x40
#define I2S_PIN_MCLK 2
#define I2S_PIN_SCLK 17
#define I2S_PIN_LRCK 45
#define I2S_PIN_DIN 16
#define I2S_PIN_DOUT 15
#endif

I2SClass i2s;

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
  i2s.setPins(I2S_PIN_SCLK, I2S_PIN_LRCK, I2S_PIN_DOUT, I2S_PIN_DIN, I2S_PIN_MCLK);
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
#if defined(OSIRIS_LICHUANG_S3)
  if (!lichuangOutput(1, false)) return false;
#else
  pinMode(46, OUTPUT);
  digitalWrite(46, LOW);
#endif
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


void boardSpeakerEnable(bool enabled) {
#if defined(OSIRIS_LICHUANG_S3)
  lichuangOutput(1, enabled);
#else
  digitalWrite(46, enabled ? HIGH : LOW);
#endif
}
esp_err_t boardAudioRead(void *data, size_t bytes, size_t *received, uint32_t timeout) {
  return i2s_channel_read(i2s.rxChan(), data, bytes, received, timeout);
}
esp_err_t boardAudioWrite(const void *data, size_t bytes, size_t *sent, uint32_t timeout) {
  return i2s_channel_write(i2s.txChan(), data, bytes, sent, timeout);
}
