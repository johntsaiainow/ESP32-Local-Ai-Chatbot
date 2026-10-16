#pragma once
#include <string>
namespace osiris_openclaw {
inline bool agentValid(const std::string &agent) {
  if (agent.empty() || agent.size() > 64) return false;
  for (unsigned char c : agent)
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.')) return false;
  return true;
}
inline bool tokenValid(const std::string &token) {
  if (token.empty() || token.size() > 256) return false;
  for (unsigned char c : token) if (c <= 32 || c >= 127) return false;
  return true;
}
// Accept a DNS/IPv4 origin, optionally ending in /v1. No credentials, query or fragments.
inline bool endpoint(std::string base, std::string &result) {
  result.clear();
  const size_t start = base.compare(0, 7, "http://") == 0 ? 7 :
                       base.compare(0, 8, "https://") == 0 ? 8 : 0;
  if (!start || base.size() > 256) return false;
  while (base.size() > start && base.back() == '/') base.pop_back();
  const size_t slash = base.find('/', start);
  if (slash != std::string::npos && base.substr(slash) != "/v1") return false;
  const std::string authority = base.substr(start, slash == std::string::npos ? slash : slash - start);
  const size_t colon = authority.find(':');
  const std::string host = authority.substr(0, colon);
  if (host.empty() || host.front() == '.' || host.front() == '-' || host.back() == '-') return false;
  for (unsigned char c : host)
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '-' || c == '.')) return false;
  if (colon != std::string::npos) {
    const std::string port = authority.substr(colon + 1);
    if (port.empty() || port.size() > 5) return false;
    unsigned value = 0;
    for (char c : port) { if (c < '0' || c > '9') return false; value = value * 10 + c - '0'; }
    if (!value || value > 65535) return false;
  }
  result = base + (slash == std::string::npos ? "/v1/chat/completions" : "/chat/completions");
  return true;
}
}
