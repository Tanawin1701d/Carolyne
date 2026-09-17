/* The smallest store-then-load test: write four words to memory, read them
 * back, print them. Nothing recursive, no branches worth speculating on. */

#include "carolyne_io.h"

int v[4];

int main(void)
{
    int i;

    for (i = 0; i < 4; i++)
        v[i] = i + 1;

    for (i = 0; i < 4; i++) {
        print_int(v[i]);
        print_char(' ');
    }
    print_char('\n');
    return 0;
}
