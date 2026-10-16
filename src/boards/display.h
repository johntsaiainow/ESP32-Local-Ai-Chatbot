#pragma once
#if defined(OSIRIS_CORE_S3) || defined(OSIRIS_ATOM_S3R)
#include "m5_display.h"
#elif defined(OSIRIS_LICHUANG_S3)
#include "lichuang_display.h"
#elif defined(OSIRIS_CROWPANEL7)
#include "crowpanel7_display.h"
#else
#include "box3_display.h"
#endif
