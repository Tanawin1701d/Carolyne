#include "carolyne_io.h"
int  w;
char b[4];
int main(void)
{
    w = 0x11; print_int(w);            /* word store then load back  */
    w = 0x22; print_int(w);
    print_char('|');
    b[0] = 'A'; print_char(b[0]);      /* byte store then load back  */
    b[1] = 'B'; print_char(b[1]);      /* same word as b[0]: RMW     */
    print_char('\n');
    return 0;
}
