/* divtest — every M-extension shape a compiled program can produce, with
 * operands the compiler cannot fold (volatile), so the machine really runs
 * div / divu / rem / remu / mul / mulh / mulhsu / mulhu. A host build of this
 * file is the oracle (`--expect host`), so no case may be undefined in C:
 * no divisor of zero and no INT_MIN / -1 here — divzero.c covers those with
 * an expected file. */

#include "carolyne_io.h"

#define N 11

static volatile int      sa[N] = { 100, -100,  100, -100,     7,    -7, 2147483647, -2147483647 - 1, 1234567, -99999,  1 };
static volatile int      sb[N] = {   7,    7,   -7,   -7,   100,   100,          3,               7,     -89,   1000, -1 };
static volatile unsigned ua[N] = { 100u, 4000000000u, 7u, 0u, 0xFFFFFFFFu, 123456789u, 65536u, 1u, 0x80000000u, 99u, 3u };
static volatile unsigned ub[N] = {   7u,          3u, 100u, 5u, 0xFFFFFFFFu, 1000u, 65536u, 0xFFFFFFFFu, 3u, 100u, 2u };

int main(void)
{
    int i;
    for (i = 0; i < N; i++) {
        int a = sa[i], b = sb[i];
        print_int(a / b); print_char(' ');
        print_int(a % b); print_char(' ');
        print_int(a * b); print_char(' ');
        print_int((int)(((long long) a * (long long) b) >> 32)); print_char('\n');
    }
    for (i = 0; i < N; i++) {
        unsigned a = ua[i], b = ub[i];
        print_int((int)(a / b)); print_char(' ');
        print_int((int)(a % b)); print_char(' ');
        print_int((int)(a * b)); print_char(' ');
        print_int((int)(((unsigned long long) a * (unsigned long long) b) >> 32)); print_char(' ');
        print_int((int)(((long long) sa[i] * (unsigned long long) b) >> 32)); print_char('\n');
    }
    finish(0);
    return 0;
}
