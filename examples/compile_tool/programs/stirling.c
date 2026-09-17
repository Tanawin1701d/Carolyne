/* stirling — from the RIDECORE test suite (app/stirling/main.c).
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

int Stirling2(int n, int k)  /* n > 0 */
{
	if (k < 1 || k > n) return 0;
	if (k == 1 || k == n) return 1;
	return k * Stirling2(n - 1, k)
			 + Stirling2(n - 1, k - 1);
}

int Stirling1(int n, int k)  /* n > 0 */
{
	if (k < 1 || k > n) return 0;
	if (k == n) return 1;
	return (n - 1) * Stirling1(n - 1, k)
				   + Stirling1(n - 1, k - 1);
}

#define N 8

int main()
{
	int n, k;

	DISPLAY_CHAR('\n');
	DISPLAY_CHAR(' ');
	DISPLAY_CHAR(' ');
	DISPLAY_CHAR('k');
	for (k = 0; k <= N; k++) DISPLAY_INT(k);
	DISPLAY_CHAR('\n');
	DISPLAY_CHAR('n');
	DISPLAY_CHAR(' ');
	DISPLAY_CHAR(' ');
	for (k = 0; k <= N; k++) {
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	}
	DISPLAY_CHAR('\n');
	for (n = 0; n <= N; n++) {
	  //		printf("%10d |", n);
	  DISPLAY_INT(n);
	  DISPLAY_CHAR(' ');
	  DISPLAY_CHAR('|');
	  for (k = 0; k <= n; k++) //printf("%10d", comb(n, k));
	    DISPLAY_INT(Stirling2(n, k));
	  DISPLAY_CHAR('\n');
	}

	DISPLAY_CHAR('\n');
	DISPLAY_CHAR(' ');
	DISPLAY_CHAR(' ');
	DISPLAY_CHAR('k');
	for (k = 0; k <= N; k++) DISPLAY_INT(k);
	DISPLAY_CHAR('\n');
	DISPLAY_CHAR('n');
	DISPLAY_CHAR(' ');
	DISPLAY_CHAR(' ');
	for (k = 0; k <= N; k++) {
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	  DISPLAY_CHAR('-');
	}
	DISPLAY_CHAR('\n');
	for (n = 0; n <= N; n++) {
	  //		printf("%10d |", n);
	  DISPLAY_INT(n);
	  DISPLAY_CHAR(' ');
	  DISPLAY_CHAR('|');
	  for (k = 0; k <= n; k++) //printf("%10d", comb(n, k));
	    DISPLAY_INT(Stirling1(n, k));
	  DISPLAY_CHAR('\n');
	}

	FINISH_PROGRAM;
	return 0;
}
