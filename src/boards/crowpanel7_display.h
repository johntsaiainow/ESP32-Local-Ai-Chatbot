#pragma once
#include <lgfx/v1/platforms/esp32s3/Panel_RGB.hpp>
#include "crowpanel7_rgb_bus.h"

// DIS08070H (basic 7-inch N4R8), not the Advance or ESP Terminal products.
// Pinout/timings: Elecrow-RD/CrowPanel-7.0-HMI-ESP32-Display-800x480.
#ifndef OSIRIS_CROW_TOUCH_ROTATION
// Use native touch axes; the previous 180-degree offset reversed reported touches.
#define OSIRIS_CROW_TOUCH_ROTATION 0
#endif
class CrowPanelLCD : public lgfx::LGFX_Device {
  CrowPanelRGBBus bus;
  lgfx::Panel_RGB panel;
  lgfx::Light_PWM light;
  lgfx::Touch_GT911 touch;
public:
  CrowPanelLCD() {
    panel.setBus(&bus);
    auto p = panel.config();
    p.panel_width = p.memory_width = 800; p.panel_height = p.memory_height = 480;
    p.pin_rst = -1; p.readable = false; panel.config(p);
    auto l = light.config(); l.pin_bl = 2; l.invert = false;
    l.freq = 44100; l.pwm_channel = 0; light.config(l); panel.setLight(&light);
    auto t = touch.config();
    t.x_min = 0; t.x_max = 799; t.y_min = 0; t.y_max = 479;
    t.offset_rotation = OSIRIS_CROW_TOUCH_ROTATION;
    // GPIO38 belongs exclusively to the microphone. GPIO15 belongs to RGB LCD.
    // V3 touch reset/interrupt selection is handled by PCA9557, not these pins.
    t.pin_int = -1; t.pin_rst = -1; t.i2c_port = I2C_NUM_0;
    t.pin_sda = 19; t.pin_scl = 20; t.freq = 400000; t.bus_shared = false;
    touch.config(t); panel.setTouch(&touch); setPanel(&panel);
  }
};
CrowPanelLCD crowLCD;
// Keep the BOX1 protocol and UI at 320x240. Render 2x at x=80 on the 800x480 LCD.
class CrowPanelCanvas : public lgfx::LGFX_Sprite {
public:
  CrowPanelCanvas() : lgfx::LGFX_Sprite(&crowLCD) {}
  void setBrightness(uint8_t value) { crowLCD.setBrightness(value); }
  bool getTouch(uint16_t *x, uint16_t *y) {
    uint16_t px = 0, py = 0;
    if (!crowLCD.getTouch(&px, &py) || px < 80 || px >= 720 || py >= 480) return false;
    *x = (px - 80) / 2; *y = py / 2; return true;
  }
};
CrowPanelCanvas lcd;
bool crowTouchWrite(uint8_t reg, uint8_t value) {
  const uint8_t bytes[] = {reg, value};
  return lgfx::i2c::transactionWrite(I2C_NUM_0, 0x18, bytes, 2, 400000).has_value();
}
bool boardDisplayBegin() {
  if (!lgfx::i2c::init(I2C_NUM_0, 19, 20).has_value()) return false;
  // V3 adds PCA9557 at 0x18. V2 has no expander and skips this sequence.
  if (crowTouchWrite(0x03, 0xFF)) {
    if (!crowTouchWrite(0x01, 0x00) || !crowTouchWrite(0x02, 0x00) || !crowTouchWrite(0x03, 0x00)) return false;
    delay(20);
    if (!crowTouchWrite(0x01, 0x01)) return false;
    delay(100);
    if (!crowTouchWrite(0x03, 0x02)) return false;
    Serial.println("CrowPanel V3 touch reset applied.");
  } else Serial.println("CrowPanel touch expander absent; using V2 initialization.");
  if (!crowLCD.init()) return false;
  crowLCD.setRotation(0); crowLCD.setBrightness(128); crowLCD.fillScreen(TFT_BLACK);
  lcd.setPsram(true); lcd.setColorDepth(16);
  return lcd.createSprite(320, 240) != nullptr;
}
void boardPollInput() {}
void boardPresent(bool force = false) {
  static uint32_t lastDraw = 0, rowHash[240] = {};
  static bool first = true;
  if (!lcd.getBuffer() || (!force && millis() - lastDraw < 100)) return;
  lastDraw = millis();
  const auto *pixels = static_cast<const uint8_t *>(lcd.getBuffer());
  int run = -1;
  lcd.setPivot(160, 120);
  for (int y = 0; y <= 240; ++y) {
    bool changed = false;
    if (y < 240) {
      const uint32_t hash = esp_rom_crc32_le(0, pixels + y * 640, 640);
      changed = first || hash != rowHash[y]; rowHash[y] = hash;
    }
    if (changed && run < 0) run = y;
    if (!changed && run >= 0) {
      // The meter/status usually changes only a few rows. Clip the affine
      // blit instead of rewriting all 614 KB of the enlarged UI each time.
      crowLCD.setClipRect(80, run * 2, 640, (y - run) * 2);
      lcd.pushRotateZoom(400, 240, 0, 2.0f, 2.0f);
      crowLCD.clearClipRect(); run = -1;
    }
  }
  first = false;
}
// GPIO0 is the running RGB pixel clock; never configure BOOT as a GPIO button.
bool boardButtonHeld() { return false; }
bool boardButtonPressed() { return false; }
constexpr const char *BOARD_NAME = "CrowPanel 7 + INMP441";
constexpr const char *BOARD_AP_PREFIX = "CrowPanel7";
