/* The smallest recursion test: one recursive call, one printed result. */
#include "carolyne_io.h"

int sum_to(int n) { if (n <= 0) return 0; return n + sum_to(n - 1); }

int main(void)
{
    print_int(sum_to(1));  print_char(' ');
    print_int(sum_to(2));  print_char(' ');
    print_int(sum_to(5));  print_char('\n');
    return 0;
}
