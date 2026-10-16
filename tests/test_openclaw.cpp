#include "../src/openclaw_utils.h"
#include <cassert>
int main() {
  std::string out;
  using namespace osiris_openclaw;
  assert(endpoint("http://192.168.1.10:18789", out));
  assert(out == "http://192.168.1.10:18789/v1/chat/completions");
  assert(endpoint("https://gateway.example/v1/", out));
  assert(out == "https://gateway.example/v1/chat/completions");
  for (auto bad : {"", "http://", "ftp://host", "http://user:pass@host", "http://host/?key=secret",
                   "http://host:0", "http://host:65536", "http://host:bad", "http://host#x",
                   "http://host/other", "http://host\r\nX: a", "http://<host>"}) assert(!endpoint(bad, out));
  assert(agentValid("default")); assert(agentValid("my-agent_2")); assert(!agentValid("a/b"));
  assert(tokenValid("gateway-secret")); assert(!tokenValid("")); assert(!tokenValid("a\r\nX:b"));
}
