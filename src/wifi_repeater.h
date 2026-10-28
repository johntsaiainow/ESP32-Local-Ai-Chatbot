#pragma once

#include "wifi_options.h"

#if OSIRIS_WIFI_REPEATER
#include <WiFi.h>
#include <Preferences.h>
#include <esp_system.h>
#include <sdkconfig.h>
#if !CONFIG_LWIP_IP_FORWARD || !CONFIG_LWIP_IPV4_NAPT
#error "Wi-Fi repeater requires an Arduino SDK with IPv4 forwarding and NAPT enabled"
#endif

// Owns the AP only outside WiFiManager's portal. All calls run on loopTask.
class WiFiRepeater {
  bool active_ = false;
  uint32_t lastAttempt_ = 0;
  bool attempted_ = false;
  IPAddress upstream_, dns_;
  String ssid_, password_;

  bool credentials() {
    if (password_.length() == 24) return true;
    Preferences prefs;
    if (!prefs.begin("osiris-repeat", false)) return false;
    password_ = prefs.getString("password", "");
    if (password_.length() != 24) {
      char generated[25];
      snprintf(generated, sizeof(generated), "%08lx%08lx%08lx",
               (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random());
      password_ = generated;
      if (!prefs.putString("password", password_)) {
        password_ = "";
        prefs.end();
        return false;
      }
    }
    prefs.end();
    ssid_ = "Osiris-Repeater-" + WiFi.macAddress().substring(9);
    ssid_.replace(":", "");
    return true;
  }

 public:
  bool active() const { return active_; }

  void stop() {
    if (!active_) return;
    WiFi.AP.enableNAPT(false);
    WiFi.AP.end();  // Retain the station interface and credentials.
    active_ = false;
    attempted_ = false;
    Serial.println("REPEATER stopped");
  }

  void poll(bool portalActive) {
    if (portalActive || WiFi.status() != WL_CONNECTED) {
      stop();
      return;
    }
    if (active_ && (upstream_ != WiFi.localIP() || dns_ != WiFi.dnsIP())) stop();
    if (active_) return;
    const uint32_t now = millis();
    if (attempted_ && now - lastAttempt_ < 10000) return;
    attempted_ = true;
    lastAttempt_ = now;
    if (!credentials()) {
      Serial.println("REPEATER cannot store credentials; retrying later");
      return;
    }
    upstream_ = WiFi.localIP();
    dns_ = WiFi.dnsIP();
    const IPAddress mask(255, 255, 255, 0);
    const IPAddress candidates[] = {IPAddress(192, 168, 50, 1), IPAddress(172, 31, 254, 1), IPAddress(10, 254, 254, 1)};
    IPAddress ap;
    for (const auto &candidate : candidates) {
      // Compare under both masks so neither subnet can contain the other.
      const uint32_t sta = (uint32_t)upstream_, other = (uint32_t)candidate;
      const uint32_t staMask = (uint32_t)WiFi.subnetMask(), apMask = (uint32_t)mask;
      if ((sta & staMask) != (other & staMask) && (sta & apMask) != (other & apMask)) {
        ap = candidate;
        break;
      }
    }
    if ((uint32_t)ap == 0) {
      Serial.println("REPEATER no non-overlapping subnet; retrying later");
      return;
    }
    IPAddress lease = ap;
    lease[3] = 2;
    const IPAddress resolver = (uint32_t)dns_ ? dns_ : IPAddress(1, 1, 1, 1);
    if (!WiFi.AP.begin() || !WiFi.softAPConfig(ap, ap, mask, lease, resolver) ||
        !WiFi.softAP(ssid_.c_str(), password_.c_str(), WiFi.channel(), 0, 4) ||
        !WiFi.AP.enableNAPT(true)) {
      WiFi.AP.end();
      Serial.println("REPEATER start failed; retrying later");
      return;
    }
    active_ = true;
    Serial.printf("REPEATER ready ssid=%s ip=%s\n", ssid_.c_str(), ap.toString().c_str());
    // Local serial provisioning only; not sent to the network or host protocol.
    Serial.printf("REPEATER password=%s\n", password_.c_str());
  }
};
#else
class WiFiRepeater {
 public:
  bool active() const { return false; }
  void stop() {}
  void poll(bool) {}
};
#endif
