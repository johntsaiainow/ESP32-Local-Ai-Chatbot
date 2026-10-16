#include "../src/cloud_voice_utils.h"
#include "../src/wake_phrase.h"
#include <assert.h>
#include <vector>
#include <stdio.h>
int main() {
  using namespace cloud_voice;
  assert(wakeOffset("Osiris, hello") == 6);
  assert(wakeOffset("Hey OSIRIS!") == 10);
  assert(wakeOffset("Orsiris hello") == SIZE_MAX);
  assert(wakeOffset("xOsiris") == SIZE_MAX);
  assert(wakeOffset("Osiris2") == SIZE_MAX);
  assert(wakeOffset("background speech") == SIZE_MAX);
  assert(wakeOffset("Hey NOVA, hello", "Hey Nova") == 8);
  assert(wakeOffset("Osiris, hello", "Nova") == SIZE_MAX);
  assert(wakeOffset("Supernova", "Nova") == SIZE_MAX);
  assert(wakeOffset("Nova2", "Nova") == SIZE_MAX);
  assert(wakeOffset("小智，你好", "小智") == 6);
  assert(wakeOffset("ねえオシリス！こんにちは", "ねえオシリス") == 18);
  assert(wakeOffset("anything", "") == SIZE_MAX);
  std::string phrase;
  assert(osiris_wake::normalize("  Hey Nova!  ", phrase) && phrase == "Hey Nova");
  assert(osiris_wake::normalize("小智！", phrase) && phrase == "小智");
  assert(osiris_wake::normalize("   ", phrase) && phrase == "Osiris");
  assert(!osiris_wake::normalize("!!!", phrase));
  assert(!osiris_wake::normalize("___", phrase));
  assert(!osiris_wake::normalize("Nova' onfocus='alert(1)", phrase));
  assert(!osiris_wake::normalize("<Nova>", phrase));
  assert(!osiris_wake::normalize("bad\x01word", phrase));
  assert(!osiris_wake::normalize("\xE5\xB0", phrase));
  assert(osiris_wake::normalize(std::string(96, 'a').c_str(), phrase));
  assert(!osiris_wake::normalize(std::string(97, 'a').c_str(), phrase));
  std::vector<uint8_t> wave(44 + 3200);
  wavHeader(wave.data(), 3200);
  PCM pcm{};
  assert(parseWav(wave.data(), wave.size(), pcm));
  assert(pcm.rate == 16000 && pcm.bytes == 3200 && pcm.data == wave.data() + 44);
  assert(!parseWav(wave.data(), wave.size() - 1, pcm));
  wave[22] = 2;
  assert(!parseWav(wave.data(), wave.size(), pcm));
  wave[22] = 1; wave[34] = 24;
  assert(!parseWav(wave.data(), wave.size(), pcm));
  wave[34] = 16; put32(wave.data() + 24, 24000);
  assert(parseWav(wave.data(), wave.size(), pcm) && pcm.rate == 24000);
  put32(wave.data() + 40, 0xffffffff);
  assert(!parseWav(wave.data(), wave.size(), pcm));
  assert(!parseWav(wave.data(), 8, pcm));
  puts("Standalone cloud audio/wake utility checks passed.");
}
