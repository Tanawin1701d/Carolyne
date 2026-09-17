/* Sub-word store then load: at -O0 print_char(char) spills its argument with
 * `sb` and reads it back with `lbu`, which no int-sized test exercises. */

#include "carolyne_io.h"

char  cbuf[4];
short hbuf[2];

int main(void)
{
    cbuf[0] = 'A'; cbuf[1] = 'B'; cbuf[2] = 'C'; cbuf[3] = 'D';
    print_char(cbuf[0]); print_char(cbuf[1]);
    print_char(cbuf[2]); print_char(cbuf[3]);
    print_char('\n');

    hbuf[0] = 0x1234; hbuf[1] = 0x5678;
    print_int(hbuf[0]); print_char(' '); print_int(hbuf[1]);
    print_char('\n');
    return 0;
}
