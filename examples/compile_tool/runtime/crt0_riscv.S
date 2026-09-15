########################################################################
# crt0.S — the reset vector, and the whole C runtime.
#
# The linker script places .text.start first in the instruction memory, so
# the core's reset PC lands on _start.
#
# There is no operating system and no libc startup. This file does the four
# things a program cannot start without: define the registers, set the
# small-data anchor, set the stack, and call main. When main returns it
# hands the value to the exit door, which is what stops the machine — the
# core retires ECALL like any other instruction, so a store is the only
# working exit.
#
# The registers are written because the architectural register file powers
# up undefined: a program that read one before writing it would read X in
# simulation.
#
# Addresses come from linker SYMBOLS the generated script defines, so this
# file states none of its own. %hi/%lo rather than `la`: absolute, and no
# relaxation to reason about.
########################################################################

    .section .text.start, "ax"
    .globl  _start
    .type   _start, @function

_start:
    # x0 is hardwired; define the other thirty-one
    .irp    n, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,15,16, \
              17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    li      x\n, 0
    .endr

    # gp — the small-data anchor. norelax so the assembler does not try to
    # reach gp through gp itself.
.option push
.option norelax
    lui     gp, %hi(__global_pointer$)
    addi    gp, gp, %lo(__global_pointer$)
.option pop

    # sp — the top of the data region, just under the I/O words
    lui     sp, %hi(__stack_top)
    addi    sp, sp, %lo(__stack_top)

    call    main

    # main returned: its value is the exit code
    lui     t0, %hi(__mmio_exit)
    addi    t0, t0, %lo(__mmio_exit)
    sw      a0, 0(t0)

_park:
    j       _park

    .size   _start, . - _start
