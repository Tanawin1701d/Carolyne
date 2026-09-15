########################################################################
# crt0_mips.S — the reset vector, and the whole C runtime, for MIPS32.
#
# The linker script places .text.start first in the instruction memory, so
# the core's reset PC lands on _start. The same four duties as the RISC-V
# file: define the registers, set the stack, call main, hand its value to
# the exit door and park.
#
# noreorder: every delay slot is written out, so what runs is what is read.
# Addresses come from linker SYMBOLS the generated script defines.
########################################################################

    .set    noreorder
    .set    noat
    .section .text.start, "ax"
    .globl  _start
    .ent    _start

_start:
    # $0 is hardwired; define the other thirty-one
    .irp    n, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,15,16, \
              17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    move    $\n, $zero
    .endr

    # $gp — the small-data anchor (unused with -G0, defined all the same)
    lui     $gp, %hi(_gp)
    addiu   $gp, $gp, %lo(_gp)

    # $sp — the top of the data region, just under the I/O words
    lui     $sp, %hi(__stack_top)
    addiu   $sp, $sp, %lo(__stack_top)

    jal     main
    nop                                 # delay slot

    # main returned: $v0 is the exit code
    lui     $t0, %hi(__mmio_exit)
    addiu   $t0, $t0, %lo(__mmio_exit)
    sw      $v0, 0($t0)

_park:
    b       _park
    nop                                 # delay slot

    .end    _start
