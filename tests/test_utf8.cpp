#include "../src/utf8.h"
#include <assert.h>
#include <initializer_list>

int main() {
  const char *text = "A\u4E2D\u65E5\uD55C\U0001F916\u2764\uFE0F";
  for (uint32_t expected : {0x41U, 0x4E2DU, 0x65E5U, 0xD55CU,
                            0x1F916U, 0x2764U, 0xFE0FU, 0U}) {
    assert(nextCodepoint(text) == expected);
  }
  const char *invalid[] = {"\x80", "\xC0\xAF", "\xE0\x80\x80",
                           "\xED\xA0\x80", "\xF4\x90\x80\x80",
                           "\xF0\x9F", "\xE4\xB8", "\xE4"};
  for (const char *input : invalid) {
    const char *cursor = input;
    assert(nextCodepoint(cursor) == 0xFFFD);
    assert(cursor == input + 1);
    while (*cursor) nextCodepoint(cursor);
  }
}
