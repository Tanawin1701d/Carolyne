/* divzero — the two divides C leaves undefined and the ISA defines: a zero
 * divisor (quotient all ones, remainder the dividend) and INT_MIN / -1
 * (INT_MIN, remainder 0). The expected output is divzero.expected — a host
 * build would trap. MIPS calls a zero divisor unpredictable; the machine
 * gives the same answers there (exec_unit_div.py). */

#include "carolyne_io.h"

static volatile int      a  = 17, b = 0;
static volatile unsigned ua = 17u, ub = 0u;
static volatile int      m  = -2147483647 - 1, n = -1;

int main(void)
{
    print_int(a / b);        print_char('\n');   /* -1          */
    print_int(a % b);        print_char('\n');   /* 17          */
    print_int((int)(ua / ub)); print_char('\n'); /* -1 (all ones) */
    print_int((int)(ua % ub)); print_char('\n'); /* 17          */
    print_int(m / n);        print_char('\n');   /* -2147483648 */
    print_int(m % n);        print_char('\n');   /* 0           */
    finish(0);
    return 0;
}
