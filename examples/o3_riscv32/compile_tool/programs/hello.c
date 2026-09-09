/* The smallest program that exercises print, arithmetic and a loop. */

#include "carolyne_io.h"

int main(void)
{
    int i;

    print_str("hello from carolyne\n");

    for (i = 0; i < 5; i++) {
        print_int(i * i);          /* rv32i has no MUL: this calls __mulsi3 */
        print_char('\n');
    }

    return 0;
}
