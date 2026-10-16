#pragma once
// LiChuang SZPI ESP32-S3 / 实战派. Pinout and PCA9557 sequencing:
// https://github.com/78/xiaozhi-esp32/tree/main/main/boards/lckfb/szpi-esp32s3
uint8_t lichuangOutputs = 0x03;
bool lichuangOutput(uint8_t bit, bool high) {
  const uint8_t value = high ? lichuangOutputs | (1 << bit) : lichuangOutputs & ~(1 << bit);
  const uint8_t command[] = {0x01, value};
  if (!lgfx::i2c::transactionWrite(I2C_NUM_0, 0x19, command, 2, 400000).has_value()) return false;
  lichuangOutputs = value; return true;
}
class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7789 panel;
  lgfx::Bus_SPI bus;
  lgfx::Light_PWM light;
  lgfx::Touch_FT5x06 touch;
public:
  LGFX() {
    auto b = bus.config();
    b.spi_host = SPI3_HOST; b.spi_mode = 2;
    b.freq_write = 40000000; b.freq_read = 16000000;
    b.spi_3wire = true;
    b.pin_sclk = 41; b.pin_mosi = 40; b.pin_miso = -1; b.pin_dc = 39;
    bus.config(b); panel.setBus(&bus);
    auto p = panel.config();
    p.pin_cs = -1; p.pin_rst = -1; p.pin_busy = -1;
    p.panel_width = 240; p.panel_height = 320;
    p.memory_width = 240; p.memory_height = 320;
    p.invert = true; p.readable = false; p.rgb_order = false;
    panel.config(p);
    auto l = light.config();
    l.pin_bl = 42; l.invert = true; l.freq = 44100; l.pwm_channel = 0;
    light.config(l); panel.setLight(&light);
    auto t = touch.config();
    t.x_min = 0; t.x_max = 239; t.y_min = 0; t.y_max = 319;
    t.offset_rotation = 0; t.pin_int = -1; t.pin_rst = -1;
    t.bus_shared = false; t.i2c_port = I2C_NUM_0;
    t.pin_sda = 1; t.pin_scl = 2; t.freq = 400000;
    touch.config(t); panel.setTouch(&touch);
    setPanel(&panel);
  }
};
LGFX lcd;
bool boardDisplayBegin() {
  pinMode(0, INPUT_PULLUP);
  if (!lgfx::i2c::init(I2C_NUM_0, 1, 2).has_value()) return false;
  // LCD reset high, amp off, camera powered down. Only bits 0..2 are outputs.
  const uint8_t output[] = {0x01, 0x05}, direction[] = {0x03, 0xF8};
  if (!lgfx::i2c::transactionWrite(I2C_NUM_0, 0x19, output, 2, 400000).has_value() ||
      !lgfx::i2c::transactionWrite(I2C_NUM_0, 0x19, direction, 2, 400000).has_value()) return false;
  lichuangOutputs = 0x05;
  delay(20); if (!lichuangOutput(0, false)) return false; delay(120);
  const bool ok = lcd.init(); lcd.setRotation(1); return ok;
}
void boardPollInput() {}
void boardPresent(bool = false) {}
bool boardButtonHeld() {
  static uint32_t pressedAt = 0;
  static bool wasDown = false, reported = false;
  const bool down = digitalRead(0) == LOW;
  if (down && !wasDown) { pressedAt = millis(); reported = false; }
  wasDown = down;
  if (down && !reported && millis() - pressedAt >= 1500) { reported = true; return true; }
  return false;
}
bool boardButtonPressed() { return false; } // Touch provides transport switching.
constexpr const char *BOARD_NAME = "LiChuang SZPI ESP32-S3";
constexpr const char *BOARD_AP_PREFIX = "LiChuangS3";
