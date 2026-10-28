#pragma once

#ifndef OSIRIS_WIFI_ENABLED
#define OSIRIS_WIFI_ENABLED 1
#endif
#ifndef OSIRIS_WIFI_REPEATER
#define OSIRIS_WIFI_REPEATER 0
#endif
// USB-only firmware always takes precedence, including custom build flags.
#if !OSIRIS_WIFI_ENABLED
#undef OSIRIS_WIFI_REPEATER
#define OSIRIS_WIFI_REPEATER 0
#endif
