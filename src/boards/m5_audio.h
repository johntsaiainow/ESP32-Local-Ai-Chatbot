#pragma once
#include <cstring>

// M5Unified owns power, codec I2C and I2S. Do not also install Arduino I2S.
// Keep protocol-facing audio stereo PCM16/16k; the application selects channel 0.
bool m5MicRunning = false;
bool m5SpeakerRunning = false;
int16_t m5Capture[2][512];
unsigned m5CaptureHead = 0, m5CaptureQueued = 0;
size_t m5CaptureOffset = 0;
bool m5CaptureReady = false;
int16_t m5Playback[3][512];
unsigned m5PlaybackNext = 0;

bool setupSD() { return false; } // Optional SD is not used by Osiris assets.
bool setupI2S() {
  auto mic = M5.Mic.config(); mic.sample_rate = 16000; M5.Mic.config(mic);
  auto spk = M5.Speaker.config(); spk.sample_rate = 16000; M5.Speaker.config(spk);
  M5.Speaker.setVolume(128);
  return psramFound();
}
bool initCodec() {
  const bool ok = M5.Mic.isEnabled() && M5.Mic.begin();
  M5.Mic.end(); return ok;
}
bool initSpeaker() {
  const bool ok = M5.Speaker.isEnabled() && M5.Speaker.begin();
  M5.Speaker.end(); return ok;
}

void boardSpeakerEnable(bool enabled) {
  if (enabled) {
    if (m5SpeakerRunning) return;
    M5.Mic.end(); // These devices share their codec/port between capture/playback.
    m5MicRunning = false; m5CaptureQueued = 0;
    m5CaptureOffset = 0; m5CaptureReady = false; m5CaptureHead = 0;
    m5SpeakerRunning = M5.Speaker.begin(); m5PlaybackNext = 0;
  } else if (m5SpeakerRunning) {
    M5.Speaker.stop(); M5.Speaker.end(); m5SpeakerRunning = false;
  }
}

esp_err_t boardAudioRead(void *data, size_t bytes, size_t *received, uint32_t timeout) {
  *received = 0;
  if (!bytes || bytes % 4 || m5SpeakerRunning) return ESP_ERR_INVALID_STATE;
  if (!m5MicRunning) {
    if (!M5.Mic.begin()) return ESP_FAIL;
    m5MicRunning = true;
    for (unsigned n = 0; n < 2; ++n) {
      if (!M5.Mic.record(m5Capture[n], 512, 16000, true)) {
        M5.Mic.end(); m5MicRunning = false; m5CaptureQueued = 0; return ESP_FAIL;
      }
      ++m5CaptureQueued;
    }
  }
  const uint32_t started = millis();
  while (!m5CaptureReady) {
    if (M5.Mic.isRecording() < m5CaptureQueued) {
      --m5CaptureQueued; m5CaptureReady = true; break;
    }
    if (millis() - started >= timeout) return ESP_ERR_TIMEOUT;
    delay(1);
  }
  const size_t count = min(bytes, sizeof(m5Capture[0]) - m5CaptureOffset);
  memcpy(data, reinterpret_cast<uint8_t *>(m5Capture[m5CaptureHead]) + m5CaptureOffset, count);
  *received = count; m5CaptureOffset += count;
  if (m5CaptureOffset == sizeof(m5Capture[0])) {
    if (!M5.Mic.record(m5Capture[m5CaptureHead], 512, 16000, true)) {
      M5.Mic.end(); m5MicRunning = false; m5CaptureQueued = 0;
      m5CaptureHead = 0; m5CaptureReady = false; m5CaptureOffset = 0;
      return ESP_FAIL;
    }
    ++m5CaptureQueued; m5CaptureHead ^= 1;
    m5CaptureOffset = 0; m5CaptureReady = false;
  }
  return ESP_OK;
}

esp_err_t boardAudioWrite(const void *data, size_t bytes, size_t *sent, uint32_t timeout) {
  *sent = 0;
  if (!m5SpeakerRunning || bytes > sizeof(m5Playback[0]) || bytes % 4) return ESP_ERR_INVALID_STATE;
  const uint32_t started = millis();
  // playRaw retains the source pointer. Three persistent buffers and a two-slot
  // queue keep stack buffers alive and allow uninterrupted DMA playback.
  while (M5.Speaker.isPlaying(0) >= 2) {
    if (millis() - started >= timeout) return ESP_ERR_TIMEOUT;
    delay(1);
  }
  auto *buffer = m5Playback[m5PlaybackNext];
  memcpy(buffer, data, bytes);
  if (!M5.Speaker.playRaw(buffer, bytes / 2, 16000, true, 1, 0)) return ESP_FAIL;
  m5PlaybackNext = (m5PlaybackNext + 1) % 3;
  *sent = bytes;
  return ESP_OK;
}
