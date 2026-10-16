// Hardware-free checks for asynchronous capture and retained playback buffers.
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <deque>
using std::min;
using esp_err_t = int;
constexpr int ESP_OK=0, ESP_FAIL=-1, ESP_ERR_TIMEOUT=1, ESP_ERR_INVALID_STATE=2;
uint32_t millis() { static uint32_t tick=0; return tick++; }
void delay(unsigned) {}
bool psramFound() { return true; }
struct Config { unsigned sample_rate=0; };
struct FakeMic {
  std::deque<int16_t*> pending;
  Config config() { return {}; } void config(Config) {}
  bool isEnabled() { return true; } bool begin() { return true; }
  void end() { pending.clear(); }
  size_t isRecording() { return pending.size(); }
  bool record(int16_t* buffer, size_t count, unsigned rate, bool stereo) {
    assert(count==512 && rate==16000 && stereo); pending.push_back(buffer); return true;
  }
  void complete(int16_t value) {
    assert(!pending.empty()); std::fill_n(pending.front(),512,value); pending.pop_front();
  }
};
struct FakeSpeaker {
  std::deque<const int16_t*> pending;
  Config config() { return {}; } void config(Config) {}
  void setVolume(unsigned) {} bool isEnabled() { return true; }
  bool begin() { return true; } void end() { pending.clear(); }
  void stop() { pending.clear(); }
  size_t isPlaying(unsigned) { return pending.size(); }
  bool playRaw(const int16_t* buffer, size_t count, unsigned rate, bool stereo, unsigned, unsigned) {
    assert(count<=512 && rate==16000 && stereo); pending.push_back(buffer); return true;
  }
};
struct { FakeMic Mic; FakeSpeaker Speaker; } M5;
#include "../src/boards/m5_audio.h"
int main() {
  assert(setupI2S() && initCodec() && initSpeaker());
  int16_t out[512]; size_t got=0;
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_ERR_TIMEOUT && got==0);
  M5.Mic.complete(100);
  assert(boardAudioRead(out,16,&got,0)==ESP_OK && got==16 && out[0]==100);
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_OK && got==1008 && out[503]==100);
  M5.Mic.complete(200);
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_OK && got==1024 && out[511]==200);
  // Two completed buffers remain ordered even if the consumer was delayed.
  M5.Mic.complete(300); M5.Mic.complete(400);
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_OK && out[0]==300);
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_OK && out[0]==400);
  boardSpeakerEnable(true);
  assert(M5.Mic.pending.empty());
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_ERR_INVALID_STATE);
  std::fill_n(out,512,11);
  assert(boardAudioWrite(out,sizeof(out),&got,0)==ESP_OK);
  std::fill_n(out,512,22);
  assert(boardAudioWrite(out,sizeof(out),&got,0)==ESP_OK);
  std::fill_n(out,512,33);
  assert(boardAudioWrite(out,sizeof(out),&got,0)==ESP_ERR_TIMEOUT);
  assert(M5.Speaker.pending[0][0]==11 && M5.Speaker.pending[1][0]==22);
  M5.Speaker.pending.pop_front();
  assert(boardAudioWrite(out,sizeof(out),&got,0)==ESP_OK);
  std::fill_n(out,512,44); M5.Speaker.pending.pop_front();
  assert(boardAudioWrite(out,sizeof(out),&got,0)==ESP_OK);
  assert(M5.Speaker.pending[0][0]==33 && M5.Speaker.pending[1][0]==44);
  boardSpeakerEnable(false);
  assert(M5.Speaker.pending.empty());
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_ERR_TIMEOUT);
  M5.Mic.complete(500);
  assert(boardAudioRead(out,sizeof(out),&got,0)==ESP_OK && out[0]==500);
}
