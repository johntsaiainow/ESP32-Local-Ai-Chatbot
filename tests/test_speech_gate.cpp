#include "../src/speech_gate.h"
#include <assert.h>

int main() {
  SpeechGate gate(80, 16000);
  for (int i = 0; i < 100; ++i) gate.feed(20, 256);
  assert(!gate.started && !gate.finished);
  gate.feed(300, 256); // A brief sound alone must not start speech.
  gate.feed(20, 256);
  assert(!gate.started);
  for (int i = 0; i < 3; ++i) gate.feed(300, 256);
  assert(gate.started && !gate.finished);
  for (int i = 0; i < 30; ++i) gate.feed(20, 256);
  assert(!gate.finished); // A short pause is allowed within the sentence.
  gate.feed(300, 256);
  for (int i = 0; i < 62; ++i) gate.feed(20, 256);
  assert(!gate.finished);
  gate.feed(20, 256);
  assert(gate.finished);
  gate.feed(300, 256);
  assert(gate.finished);
}
