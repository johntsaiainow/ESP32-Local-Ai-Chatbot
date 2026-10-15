#pragma once
#include <stddef.h>
#include <stdint.h>

// Serial transports may accept only part of a buffer. Never discard its tail.
template <typename Writer>
bool writeFully(Writer &writer, const uint8_t *data, size_t length) {
  while (length) {
    const size_t written = writer.write(data, length);
    if (!written || written > length) return false;
    data += written;
    length -= written;
  }
  return true;
}
