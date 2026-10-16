#pragma once
#include "../i2s_pcm.h"
#ifndef OSIRIS_INMP441_GAIN
#define OSIRIS_INMP441_GAIN 4
#endif
static_assert(OSIRIS_INMP441_GAIN >= 1 && OSIRIS_INMP441_GAIN <= 32, "INMP441 gain must be 1..32");

// Standard I2S, 16 kHz, two 32-bit slots = 64 BCLK per frame. INMP441 (L/R=GND)
// supplies the left channel; NS4168 gets duplicated left/right speaker audio.
// No MCLK, ES7210/ES8311 I2C setup, RGB LED output or GPIO37 use on this board.
i2s_chan_handle_t crowAudioTX = nullptr, crowAudioRX = nullptr;
bool crowSpeakerEnabled = false;
// The playback task has a 4 KB stack. Keep slot conversion buffers off-stack.
// Capture runs on loop(); playback has a single owner, as on the other boards.
alignas(4) int32_t crowRXSlots[512], crowTXSlots[512];
bool setupSD() { return false; } // Bundled assets do not require SD.
void crowAudioEnd() {
  if (crowAudioRX) { i2s_channel_disable(crowAudioRX); i2s_del_channel(crowAudioRX); crowAudioRX = nullptr; }
  if (crowAudioTX) { i2s_channel_disable(crowAudioTX); i2s_del_channel(crowAudioTX); crowAudioTX = nullptr; }
}
bool setupI2S() {
  i2s_chan_config_t cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cfg.dma_desc_num = 6; cfg.dma_frame_num = 240;
  cfg.auto_clear_after_cb = true;
  if (i2s_new_channel(&cfg, &crowAudioTX, &crowAudioRX) != ESP_OK) return false;
  i2s_std_config_t stdCfg = {};
  stdCfg.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000);
  stdCfg.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO);
  stdCfg.gpio_cfg.mclk = I2S_GPIO_UNUSED;
  stdCfg.gpio_cfg.bclk = GPIO_NUM_42; stdCfg.gpio_cfg.ws = GPIO_NUM_18;
  stdCfg.gpio_cfg.dout = GPIO_NUM_17; stdCfg.gpio_cfg.din = GPIO_NUM_38;
  if (i2s_channel_init_std_mode(crowAudioTX, &stdCfg) != ESP_OK ||
      i2s_channel_init_std_mode(crowAudioRX, &stdCfg) != ESP_OK ||
      i2s_channel_enable(crowAudioTX) != ESP_OK || i2s_channel_enable(crowAudioRX) != ESP_OK) {
    crowAudioEnd(); return false;
  }
  return true;
}
bool initCodec() {
  // INMP441 has no identity/configuration registers. Successful driver setup
  // does not detect a missing microphone; inspect the meter/recorded WAV.
  if (crowAudioRX) Serial.println("INMP441 input configured on GPIO38 (left slot); check recorded audio to verify wiring.");
  return crowAudioRX != nullptr;
}
bool initSpeaker() { return crowAudioTX != nullptr; }
void boardSpeakerEnable(bool enabled) {
  // NS4168 has no separate enable GPIO here. Keep clocks running for the mic;
  // auto-clear DMA emits silence when there is no speaker data.
  crowSpeakerEnabled = enabled;
}
esp_err_t boardAudioRead(void *data, size_t bytes, size_t *received, uint32_t timeout) {
  *received = 0;
  if (!crowAudioRX || !bytes || bytes % 4) return ESP_ERR_INVALID_ARG;
  size_t rawBytes = 0;
  const size_t frames = min(bytes / 4, size_t(256));
  const esp_err_t error = i2s_channel_read(crowAudioRX, crowRXSlots, frames * 8, &rawBytes, timeout);
  if (rawBytes % 8) return ESP_FAIL;
  auto *pcm = static_cast<int16_t *>(data);
  for (size_t n = 0; n < rawBytes / 8; ++n) {
    const int16_t sample = osiris_pcm::gain16(osiris_pcm::fromSlot32(crowRXSlots[n * 2]), OSIRIS_INMP441_GAIN);
    pcm[n * 2] = pcm[n * 2 + 1] = sample;
  }
  *received = rawBytes / 2; return error;
}
esp_err_t boardAudioWrite(const void *data, size_t bytes, size_t *sent, uint32_t timeout) {
  *sent = 0;
  if (!crowAudioTX || !crowSpeakerEnabled || !bytes || bytes % 4 || bytes > 1024) return ESP_ERR_INVALID_ARG;
  const auto *pcm = static_cast<const int16_t *>(data);
  for (size_t n = 0; n < bytes / 2; ++n) crowTXSlots[n] = osiris_pcm::toSlot32(pcm[n]);
  size_t rawBytes = 0;
  const esp_err_t error = i2s_channel_write(crowAudioTX, crowTXSlots, bytes * 2, &rawBytes, timeout);
  if (rawBytes % 8) return ESP_FAIL;
  *sent = rawBytes / 2; return error;
}
