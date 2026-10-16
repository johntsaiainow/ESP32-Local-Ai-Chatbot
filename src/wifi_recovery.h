#pragma once
#include <stdint.h>
namespace osiris_wifi {
// Let SDK auto-reconnect run first, then recover persistent disconnects.
// Setup portals own networking; never interfere with provisioning.
class Recovery {
 public:
  bool poll(uint32_t now, bool connected, bool provisioning) {
    if (connected) { armed_ = true; waiting_ = false; return false; }
    if (!armed_ || provisioning) { waiting_ = false; return false; }
    if (!waiting_) { waiting_ = true; since_ = now; interval_ = 5000; return false; }
    if (uint32_t(now-since_) < interval_) return false;
    since_ = now;
    interval_ = interval_ < 30000 ? (interval_*2 > 30000 ? 30000 : interval_*2) : 30000;
    return true;
  }
  bool recovering() const { return waiting_; }
 private:
  bool armed_ = false, waiting_ = false;
  uint32_t since_ = 0, interval_ = 5000;
};
}
