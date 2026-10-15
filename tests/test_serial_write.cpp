#include "../src/serial_write.h"
#include <algorithm>
#include <assert.h>
#include <string>

struct ShortWriter {
  std::string output;
  size_t limit = 7;
  size_t write(const uint8_t *data, size_t size) {
    const size_t count = std::min(limit, size);
    output.append(reinterpret_cast<const char *>(data), count);
    return count;
  }
};

int main() {
  const std::string frame = "BOX1 DATA " + std::string(128, 'a') + "\n";
  ShortWriter writer;
  assert(writeFully(writer, reinterpret_cast<const uint8_t *>(frame.data()), frame.size()));
  assert(writer.output == frame);
  writer.limit = 0;
  assert(!writeFully(writer, reinterpret_cast<const uint8_t *>(frame.data()), frame.size()));
}
