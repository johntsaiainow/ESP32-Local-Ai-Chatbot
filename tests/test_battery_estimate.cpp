#include "battery_estimate.h"
#include <cassert>
int main() {
  using namespace osiris_battery;
  assert(batteryMillivolts(1000) == 4010);
  assert(batteryMillivolts(0) == 0);
  assert(percent(3300) == 0);
  assert(percent(3800) == 50);
  assert(percent(3850) == 60);
  assert(percent(4200) == 100);
  for (unsigned mv = 2501; mv <= 4300; ++mv) {
    assert(percent(mv) >= percent(mv - 1));
    assert(percent(mv) >= 0 && percent(mv) <= 100);
  }
}
