/* fib — from the RIDECORE test suite (app/fib/main.c).
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
int outchar(int a) {  
  print_char(a);  
  return 0;
}

int outnum(int num) {
  print_int(num);
  return 0;
}

void DISPLAY_INT(int n) {
  int i;
  int temp;
  for (i = 7 ; i >= 0 ; i--) {
    temp = (n >> 4*i) & 0x0f;
    outchar(temp >= 10 ? (temp+55) : (temp+48));
  }
  return;
}

int fib(int n) {
  if (n < 3)
    return 1;
  else 
    return fib(n-1)+fib(n-2);
}

int main(void) {
  //outnum(fib(3));
  //print_int(fib(13));
  DISPLAY_INT(fib(13));
  print_char('\n');
  print_char('B');
  outchar('A');
  finish(0);
  return 0;
}
