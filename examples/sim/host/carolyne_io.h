/* The host stand-in for the generated carolyne_io.h, so the SAME C source can
 * be compiled natively and run as the oracle a simulation is checked against.
 *
 * Only the four calls a program makes are defined, and each does on the host
 * what the machine's I/O word does in hardware. No address is named here: the
 * doors are the machine's, and a host program never reaches them. */

#ifndef CAROLYNE_IO_H
#define CAROLYNE_IO_H

#include <stdio.h>
#include <stdlib.h>

static inline void print_char(char value)       { fputc(value, stdout);       }
static inline void print_int (int value)        { printf("%d", value);        }
static inline void print_str (const char *text) { fputs(text, stdout);        }
static inline void finish    (int code)         { fflush(stdout); exit(code); }

#endif /* CAROLYNE_IO_H */
