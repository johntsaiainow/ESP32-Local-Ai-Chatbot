#pragma once
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
    // BOX-3 touch axes are mounted 180 degrees from the panel's native axes.
    // Let LGFX combine this offset with lcd.setRotation(2) for all getTouch calls.
    t_cfg.offset_rotation = 2;
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

bool boardDisplayBegin() {
  pinMode(LCD_PIN_RESET, OUTPUT);
  digitalWrite(LCD_PIN_RESET, HIGH); delay(20);
  digitalWrite(LCD_PIN_RESET, LOW); delay(120);
  const bool ok = lcd.init(); lcd.setRotation(2); return ok;
}
void boardPollInput() {}
void boardPresent(bool = false) {}
bool boardButtonPressed() { return false; }
bool boardButtonHeld() { return false; }
constexpr const char *BOARD_NAME = "ESP32-S3-BOX-3";
constexpr const char *BOARD_AP_PREFIX = "BOX3";

