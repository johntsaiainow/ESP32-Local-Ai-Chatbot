#include "../src/wifi_recovery.h"
#include <cassert>
int main() {
  osiris_wifi::Recovery wifi;
  assert(!wifi.poll(0, false, false));
  assert(!wifi.poll(60000, false, false)); // Startup provisioning owns initial failure.
  assert(!wifi.recovering());
  assert(!wifi.poll(60001, true, false));
  assert(!wifi.poll(61000, false, false));
  assert(wifi.recovering());
  assert(!wifi.poll(65999, false, false));
  assert(wifi.poll(66000, false, false));
  assert(!wifi.poll(75999, false, false));
  assert(wifi.poll(76000, false, false));
  assert(wifi.poll(96000, false, false));
  assert(!wifi.poll(125999, false, false));
  assert(wifi.poll(126000, false, false));
  assert(!wifi.poll(126001, false, true));
  assert(!wifi.recovering()); // Portal must never trigger station requests.
  assert(!wifi.poll(200000, false, true));
  assert(!wifi.poll(200001, false, false));
  assert(!wifi.poll(200002, true, false));
  assert(!wifi.recovering());
  assert(!wifi.poll(200003, false, false));
  assert(wifi.poll(205003, false, false)); // Success resets backoff.
  osiris_wifi::Recovery wrap;
  assert(!wrap.poll(0xfffffff0u, true, false));
  assert(!wrap.poll(0xfffffff1u, false, false));
  assert(!wrap.poll(0x100u, false, false));
  assert(wrap.poll(uint32_t(0xfffffff1u + 5000u), false, false));
}
