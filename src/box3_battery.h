#pragma once
#include "battery_estimate.h"
#ifndef OSIRIS_BOX3_BATTERY
#define OSIRIS_BOX3_BATTERY 0
#endif
#if OSIRIS_BOX3_BATTERY && !defined(OSIRIS_CORE_S3) && !defined(OSIRIS_ATOM_S3R) && !defined(OSIRIS_CROWPANEL7) && !defined(OSIRIS_LICHUANG_S3)
constexpr bool BOX3_BATTERY_SUPPORTED = true;
const char *readBattery(uint32_t &millivolts, int &percent) {
  constexpr uint8_t pin = 10;
  static bool initialized = false;
  if (!initialized) {
    pinMode(pin, INPUT);
    analogSetPinAttenuation(pin, ADC_6db);
    initialized = true;
  }
  analogReadMilliVolts(pin); // Discard first conversion after configuration.
  uint32_t total = 0;
  for (unsigned i = 0; i < 16; ++i) {
    total += analogReadMilliVolts(pin);
    delay(2);
  }
  millivolts = osiris_battery::batteryMillivolts((total + 8) / 16);
  // Very low or out-of-range voltage cannot establish battery presence or SOC.
  percent = millivolts >= 2500 && millivolts <= 4300 ? osiris_battery::percent(millivolts) : -1;
  return nullptr;
}
#else
constexpr bool BOX3_BATTERY_SUPPORTED = false;
const char *readBattery(uint32_t &, int &) { return "battery_disabled"; }
#endif
