#pragma once
// BOX-3-SENSOR AHT30: dedicated dock bus, separate from audio/touch.
#ifndef OSIRIS_BOX3_ENVIRONMENT
#define OSIRIS_BOX3_ENVIRONMENT 0
#endif
#if OSIRIS_BOX3_ENVIRONMENT && !defined(OSIRIS_CORE_S3) && !defined(OSIRIS_ATOM_S3R) && !defined(OSIRIS_CROWPANEL7) && !defined(OSIRIS_LICHUANG_S3)
constexpr bool BOX3_ENVIRONMENT_SUPPORTED = true;
TwoWire environmentWire(1);
const char *readEnvironment(float &temperature, float &humidity) {
  static bool initialized = false;
  if (!initialized) {
    if (!environmentWire.begin(41, 40, 100000)) return "sensor_bus";
    environmentWire.setTimeOut(50);
    initialized = true;
  }
  environmentWire.beginTransmission(0x38);
  const uint8_t command[] = {0xAC, 0x33, 0x00};
  environmentWire.write(command, sizeof(command));
  if (environmentWire.endTransmission() != 0) return "sensor_missing";
  delay(80);
  uint8_t data[7];
  const uint32_t started = millis();
  do {
    if (environmentWire.requestFrom(uint8_t(0x38), uint8_t(7)) != 7) return "sensor_read";
    for (auto &byte : data) byte = environmentWire.read();
    if (!(data[0] & 0x80)) break;
    if (millis() - started >= 200) return "sensor_busy";
    delay(10);
  } while (true);
  if (!(data[0] & 0x08)) return "sensor_uncalibrated";
  uint8_t crc = 0xFF;
  for (unsigned i = 0; i < 6; ++i) {
    crc ^= data[i];
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : crc << 1;
  }
  if (crc != data[6]) return "sensor_crc";
  const uint32_t rh = (uint32_t(data[1]) << 12) | (uint32_t(data[2]) << 4) | (data[3] >> 4);
  const uint32_t t = (uint32_t(data[3] & 15) << 16) | (uint32_t(data[4]) << 8) | data[5];
  humidity = rh * (100.0f / 1048576.0f);
  temperature = t * (200.0f / 1048576.0f) - 50.0f;
  return nullptr;
}
#else
constexpr bool BOX3_ENVIRONMENT_SUPPORTED = false;
const char *readEnvironment(float &, float &) { return "sensor_unsupported"; }
#endif
