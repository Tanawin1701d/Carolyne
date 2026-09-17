/* riscv_temp — from the RIDECORE test suite (app/riscv_temp/main.c).
 * Copyright (c) 2016 Arch Lab. Tokyo Institute of Technology — the
 * conditions and disclaimer are in LICENSE.ridecore, this directory.
 * The algorithm is unchanged; only the three MMIO doors became the four
 * carolyne_io.h calls, so a host build of this file is a valid oracle.
 */

#include "carolyne_io.h"

/*************************************************
Libraries
**************************************************/
//volatile char* disp = (char*)(0);
//volatile char* finish = (char*)(1);
void outchar(char a) {  print_char(a);  }

void outstring(char* str) {  while (*str != '\0')  print_char(*(str++)); }

void outnum(int num) {
  print_int(num);
}

int fib(int n) {
  if (n < 3)
    return 1;
  else 
    return fib(n-1)+fib(n-2);
}

void main(void) {
  //outnum(fib(5));
  outchar('A');
  print_char('B');
  finish(0);
}
