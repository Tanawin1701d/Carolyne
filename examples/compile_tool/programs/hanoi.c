/* hanoi — from the RIDECORE test suite (app/hanoi/main.c).
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
#define DISPLAY_CHAR(chr) print_char(chr)
#define FINISH_PROGRAM finish(0)
//#define DISPLAY_INT(num) *((int*)(intdisp_addr)) = num
#define TEST 1

void DISPLAY_INT(int n) {
  int i;
  int temp;
  for (i = 7 ; i >= 0 ; i--) {
    temp = (n >> 4*i) & 0x0f;
    DISPLAY_CHAR(temp >= 10 ? (temp+55) : (temp+48));
  }
  return;
}

void outchar(int a) {  
  print_char(a);  
  return;
}

void Hanoi(int n,int x,int y) {
  if(n>=2) Hanoi(n-1,x,6-x-y);

  //  printf("%d %d %d\n",n,x,y);
  DISPLAY_INT(n);
  outchar(' ');
  DISPLAY_INT(x);
  outchar(' ');
  DISPLAY_INT(y);
  outchar('\n');

  if(n>=2) Hanoi(n-1,6-x-y,y);
  return;
}

int main(void) {
  Hanoi(5,1,5);
  finish(0);
  return 0;
}

