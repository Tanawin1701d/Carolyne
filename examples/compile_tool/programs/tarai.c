/* tarai — from the RIDECORE test suite (app/tarai/main.c).
 * Copyright (c) 2016 Arch Lab. Tokyo Institute of Technology — the
 * conditions and disclaimer are in LICENSE.ridecore, this directory.
 * The algorithm is unchanged; only the three MMIO doors became the four
 * carolyne_io.h calls, so a host build of this file is a valid oracle.
 */

#include "carolyne_io.h"
#define DISPLAY_CHAR(chr) print_char(chr)
#define FINISH_PROGRAM finish(0)
//#define DISPLAY_INT(num) *((int*)(intdisp_addr)) = num

void DISPLAY_INT(int n) {
  int i;
  int temp;
  for (i = 7 ; i >= 0 ; i--) {
    temp = (n >> 4*i) & 0x0f;
    DISPLAY_CHAR(temp >= 10 ? (temp+55) : (temp+48));
  }
  return;
}

int tarai(int x, int y, int z)
{
	if (x <= y) return y;
	return tarai(tarai(x - 1, y, z),
				 tarai(y - 1, z, x),
				 tarai(z - 1, x, y));
}

int main(void) {
  int x, y, z;
  x=8;
  y=4;
  z=0;
  DISPLAY_INT(tarai(x, y, z));
  DISPLAY_CHAR('\n');
  FINISH_PROGRAM;
  return 0;
}
