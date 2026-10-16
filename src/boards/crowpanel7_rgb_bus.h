#pragma once
#include <esp_lcd_panel_rgb.h>
#include <esp_lcd_panel_ops.h>

#ifndef OSIRIS_CROW_PCLK_HZ
#define OSIRIS_CROW_PCLK_HZ 12000000
#endif
static_assert(OSIRIS_CROW_PCLK_HZ >= 8000000 && OSIRIS_CROW_PCLK_HZ <= 20000000,
              "CrowPanel pixel clock must be 8..20 MHz");

// Keep LovyanGFX's drawing/emoji/touch, but let the supported ESP-IDF driver
// own RGB DMA and VSYNC. The legacy LGFX Bus_RGB uses a private DMA/ISR path
// without SRAM bounce buffers, which is fragile under PSRAM/Wi-Fi contention.
class CrowPanelRGBBus : public lgfx::Bus_NULL {
  esp_lcd_panel_handle_t handle = nullptr;
  uint8_t *frame = nullptr;
public:
  bool init() override {
    if (handle) return true;
    esp_lcd_rgb_panel_config_t cfg = {};
    cfg.clk_src = LCD_CLK_SRC_DEFAULT;
    cfg.data_width = 16; cfg.bits_per_pixel = 16; cfg.num_fbs = 1;
    cfg.dma_burst_size = 64;
    cfg.bounce_buffer_size_px = 800 * 10; // Two 16 KB internal DMA buffers.
    cfg.flags.fb_in_psram = true;
    // Do not invalidate CPU-written framebuffer cache from the bounce ISR.
    cfg.flags.bb_invalidate_cache = false;
    cfg.hsync_gpio_num = 39; cfg.vsync_gpio_num = 40;
    cfg.de_gpio_num = 41; cfg.pclk_gpio_num = 0; cfg.disp_gpio_num = -1;
    const int pins[] = {15, 7, 6, 5, 4, 9, 46, 3, 8, 16, 1, 14, 21, 47, 48, 45};
    // Panel_RGB stores byte-swapped RGB565. Legacy LGFX Bus_RGB routes
    // physical D0..D7 to LCD signals 8..15 and D8..D15 to signals 0..7.
    // Preserve that byte swap in IDF's signal-indexed pin table; otherwise
    // yellow/orange emoji pixels acquire blue/purple components.
    for (unsigned n = 0; n < 16; ++n) cfg.data_gpio_nums[n] = pins[n ^ 8u];
    auto &t = cfg.timings;
    t.pclk_hz = OSIRIS_CROW_PCLK_HZ; t.h_res = 800; t.v_res = 480;
    t.hsync_front_porch = 40; t.hsync_pulse_width = 48; t.hsync_back_porch = 40;
    t.vsync_front_porch = 1; t.vsync_pulse_width = 31; t.vsync_back_porch = 13;
    // Match the previous register-level idle polarities (0 = idle low).
    t.flags.hsync_idle_low = true; t.flags.vsync_idle_low = true;
    t.flags.pclk_active_neg = true;
    esp_err_t error = esp_lcd_new_rgb_panel(&cfg, &handle);
    void *buffer = nullptr;
    if (error == ESP_OK) error = esp_lcd_rgb_panel_get_frame_buffer(handle, 1, &buffer);
    if (error == ESP_OK && !buffer) error = ESP_ERR_NO_MEM;
    if (error == ESP_OK) {
      frame = static_cast<uint8_t *>(buffer);
      memset(frame, 0, 800 * 480 * 2);
      error = esp_lcd_panel_reset(handle);
    }
    if (error == ESP_OK) error = esp_lcd_panel_init(handle);
    if (error != ESP_OK) {
      Serial.printf("CrowPanel RGB init failed: %s\n", esp_err_to_name(error));
      release(); return false;
    }
    Serial.printf("CrowPanel RGB: ESP-IDF DMA, %u Hz PCLK, 2x16 KB SRAM bounce buffers\n",
                  unsigned(OSIRIS_CROW_PCLK_HZ));
    return true;
  }
  void release() override {
    if (handle) esp_lcd_panel_del(handle);
    handle = nullptr; frame = nullptr;
  }
  uint8_t *getDMABuffer(uint32_t length) override {
    return length <= 800 * 480 * 2 ? frame : nullptr;
  }
  bool writeCommand(uint32_t, uint_fast8_t) override { return true; }
};
