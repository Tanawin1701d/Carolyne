/* The smallest program that exercises print, arithmetic and a loop. */

#include "carolyne_io.h"

int main(void)
{
    int i;

    print_str("hello from carolyne\n");

    for (i = 0; i < 5; i++) {
        print_int(i * i);          /* a real MUL: the muldiv station runs it */
        print_char('\n');
    }

    return 0;
}
