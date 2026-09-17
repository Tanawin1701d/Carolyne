/* cprime — from the RIDECORE test suite (app/cprime/main.c).
 * Copyright (c) 2016 Arch Lab. Tokyo Institute of Technology — the
 * conditions and disclaimer are in LICENSE.ridecore, this directory.
 * The algorithm is unchanged; only the three MMIO doors became the four
 * carolyne_io.h calls, so a host build of this file is a valid oracle.
 */

#include "carolyne_io.h"
#define DISPLAY_CHAR(chr) print_char(chr)
#define FINISH_PROGRAM finish(0)
#define DISPLAY_INT(num) *((int*)(intdisp_addr)) = num

#define N 39
#define SQRTN 6  /* floor(sqrt(N)) */
//char a[N + 1][N + 1];
int a[N + 1][N + 1];
int main()
{
	int i, j, p, q, x, y;

	for (i = 0; i <= N; i++)
		for (j = 0; j <= N; j++) a[i][j] = 1;
	a[0][0] = a[1][0] = a[0][1] = 0;
	for (i = 1; i <= SQRTN; i++) {
		for (j = 0; j <= i; j++) {
			if (a[i][j]) {
				p = i;  q = j;
				do {
					x = p;  y = q;
					do {
						a[x][y] = a[y][x] = 0;
					} while ((x -= j) >= 0 && (y += i) <= N);
					x = p;  y = q;
					do {
						a[x][y] = a[y][x] = 0;
					} while ((x += j) <= N && (y -= i) >= 0);
					p += i;  q += j;
				} while (p <= N);
				a[i][j] = a[j][i] = 1;
			}
		}
	}
	for (i = -N; i <= N; i++) {
		for (j = -N; j <= N; j++) {
		  if (a[i >= 0 ? i : -i][j >= 0 ? j : -j] && i * i + j * j <= N * N)
			  DISPLAY_CHAR('*');
			else
			  DISPLAY_CHAR(' ');
		}
		DISPLAY_CHAR('\n');
	}
	FINISH_PROGRAM;
	return 0;
}
