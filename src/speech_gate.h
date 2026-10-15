#pragma once
#include <stddef.h>
#include <stdint.h>

// Frame-based endpointing; elapsed audio frames, not USB transfer time.
class SpeechGate {
 public:
  SpeechGate(int threshold, size_t silenceSamples)
      : threshold_(threshold), silenceSamples_(silenceSamples) {}
  bool started = false;
  bool finished = false;
  void feed(int meanAmplitude, size_t samples) {
    if (finished) return;
    if (meanAmplitude >= threshold_) {
      voiced_ += samples;
      quiet_ = 0;
      if (voiced_ >= 768) started = true; // Require 48 ms of speech.
    } else {
      voiced_ = 0;
      if (started) {
        quiet_ += samples;
        if (quiet_ >= silenceSamples_) finished = true;
      }
    }
  }
 private:
  int threshold_;
  size_t silenceSamples_;
  size_t voiced_ = 0;
  size_t quiet_ = 0;
};
