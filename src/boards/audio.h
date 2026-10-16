#pragma once
#if defined(OSIRIS_CORE_S3) || defined(OSIRIS_ATOM_S3R)
#include "m5_audio.h"
#elif defined(OSIRIS_CROWPANEL7)
#include "crowpanel7_audio.h"
#else
#include "box_audio.h"
#endif
