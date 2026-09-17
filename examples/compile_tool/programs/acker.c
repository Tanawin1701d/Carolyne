/* acker — from the RIDECORE test suite (app/acker/main.c).
 * Copyright (c) 2016 Arch Lab. Tokyo Institute of Technology — the
 * conditions and disclaimer are in LICENSE.ridecore, this directory.
 * The algorithm is unchanged; only the three MMIO doors became the four
 * carolyne_io.h calls, so a host build of this file is a valid oracle.
 */

#include "carolyne_io.h"
#define DISPLAY_CHAR(chr) print_char(chr)
#define FINISH_PROGRAM finish(0)
//#define DISPLAY_INT(num) *((int*)(intdisp_addr)) = num
#define TEST 1

#if TEST
	int count = 0;
#endif

void DISPLAY_INT(int n) {
  int i;
  int temp;
  for (i = 7 ; i >= 0 ; i--) {
    temp = (n >> 4*i) & 0x0f;
    DISPLAY_CHAR(temp > 10 ? (temp+55) : (temp+48));
  }
  return;
}

int A(int x, int y)
{
	#if TEST
		count++;
	#endif
	if (x == 0) return y + 1;
	if (y == 0) return A(x - 1, 1);
	return A(x - 1, A(x, y - 1));
}

int main()
{
  DISPLAY_INT(A(3,3));
  DISPLAY_CHAR('\n');
#if TEST
  DISPLAY_INT(count);
  DISPLAY_CHAR('\n');
#endif
  FINISH_PROGRAM;
  return 0;
}

