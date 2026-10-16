#pragma once
#include <M5Unified.h>

// Preserve the existing 320x240 UI/protocol coordinates on smaller displays.
// M5GFX is derived from LovyanGFX; use its copy of lgfx throughout M5 builds.
class OsirisCanvas : public M5Canvas {
public:
  OsirisCanvas() : M5Canvas(&M5.Display) {}
  void setBrightness(uint8_t value) { M5.Display.setBrightness(value); }
  bool getTouch(uint16_t *x, uint16_t *y) {
    if (!M5.Touch.getCount()) return false;
    const auto point = M5.Touch.getDetail();
    const float scale = min(M5.Display.width() / 320.0f, M5.Display.height() / 240.0f);
    const int left = (M5.Display.width() - 320 * scale) / 2;
    const int top = (M5.Display.height() - 240 * scale) / 2;
    if (point.x < left || point.y < top || point.x >= left + 320 * scale ||
        point.y >= top + 240 * scale) return false;
    *x = (point.x - left) / scale; *y = (point.y - top) / scale;
    return true;
  }
};
OsirisCanvas lcd;
bool boardDisplayBegin() {
  auto cfg = M5.config();
  cfg.serial_baudrate = 0;
  cfg.internal_spk = true;
  cfg.internal_mic = true;
#if defined(OSIRIS_ATOM_S3R)
  cfg.fallback_board = m5::board_t::board_M5AtomS3R;
  cfg.external_speaker.atomic_echo = true; // Required Echo Base, not Atomic SPK.
#else
  cfg.fallback_board = m5::board_t::board_M5StackCoreS3;
#endif
  M5.begin(cfg);
#if defined(OSIRIS_CORE_S3)
  M5.Display.setRotation(1);
#else
  M5.Display.setRotation(0);
#endif
  M5.Display.setBrightness(128);
  M5.Display.fillScreen(TFT_BLACK);
  lcd.setPsram(true);
  lcd.setColorDepth(16);
  return lcd.createSprite(320, 240) != nullptr;
}
void boardPollInput() { M5.update(); }
void boardPresent(bool force = false) {
  static uint32_t lastDraw = 0;
  static uint32_t lastHash = 0;
  static bool firstFrame = true;
  if (!lcd.getBuffer() || (!force && millis() - lastDraw < 100)) return;
  lastDraw = millis();
  const uint32_t hash = esp_rom_crc32_le(0, static_cast<const uint8_t *>(lcd.getBuffer()), 320 * 240 * 2);
  if (!firstFrame && hash == lastHash) return;
  firstFrame = false; lastHash = hash;
  const float scale = min(M5.Display.width() / 320.0f, M5.Display.height() / 240.0f);
  lcd.setPivot(160, 120);
  lcd.pushRotateZoom(M5.Display.width() / 2.0f, M5.Display.height() / 2.0f, 0, scale, scale);
}
bool boardButtonHeld() {
  static bool reported = false;
  if (!M5.BtnA.isPressed()) { reported = false; return false; }
  if (!reported && M5.BtnA.pressedFor(1500)) { reported = true; return true; }
  return false;
}
bool boardButtonPressed() { return M5.BtnA.wasClicked(); }
#if defined(OSIRIS_CORE_S3)
constexpr const char *BOARD_NAME = "M5Stack CoreS3";
constexpr const char *BOARD_AP_PREFIX = "CoreS3";
#else
constexpr const char *BOARD_NAME = "AtomS3R + Echo Base";
constexpr const char *BOARD_AP_PREFIX = "AtomS3R";
#endif
