#pragma once
#include <stdint.h>

namespace osiris_battery {
// Coarse single-cell Li-ion voltage estimate; not a fuel-gauge measurement.
inline int percent(uint32_t mv) {
  const uint16_t voltages[] = {3300, 3600, 3700, 3800, 3900, 4000, 4100, 4200};
  const uint8_t levels[] = {0, 10, 30, 50, 70, 85, 95, 100};
  if (mv <= voltages[0]) return 0;
  for (unsigned i = 1; i < sizeof(levels); ++i) {
    if (mv <= voltages[i])
      return levels[i - 1] + (mv - voltages[i - 1]) * (levels[i] - levels[i - 1]) /
                              (voltages[i] - voltages[i - 1]);
  }
  return 100;
}
inline uint32_t batteryMillivolts(uint32_t adcMv) {
  // Official SENSOR-01 V1.1: R15=301K, R16=100K, GPIO10.
  return (adcMv * 401u + 50u) / 100u;
}
}
