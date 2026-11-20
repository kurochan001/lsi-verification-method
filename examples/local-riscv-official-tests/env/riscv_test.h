// Machine-mode environment of this example for the rv32ui tests of riscv-tests.
//
// riscv-tests asks each target to provide riscv_test.h with these macro names. This file is
// written for the core of this repository and is not a copy of the upstream "p" environment:
// it touches only mtvec and mcause, ends with EBREAK after the store to tohost, and uses no
// FENCE. README.md explains why the upstream environment is not used.
#ifndef LOCAL_RISCV_OFFICIAL_TESTS_ENV_H
#define LOCAL_RISCV_OFFICIAL_TESTS_ENV_H

#define RVTEST_RV32U .macro init; .endm
#define RVTEST_RV64U RVTEST_RV32U
#define TESTNUM gp
#define UNEXPECTED_TRAP 0x400   // set in tohost when the trap was not the ECALL of pass or fail

#define RVTEST_CODE_BEGIN                                               \
        .section .text.init;                                            \
        .globl _start;                                                  \
_start: j reset_vector;                                                 \
trap_vector:                                                            \
        csrr t5, mcause;                                                \
        li t6, 11;                                                      \
        beq t5, t6, write_tohost;                                       \
        ori TESTNUM, TESTNUM, UNEXPECTED_TRAP;                          \
write_tohost:                                                           \
        la t5, tohost;                                                  \
        sw TESTNUM, 0(t5);                                              \
        ebreak;                                                         \
reset_vector:                                                           \
        li x1, 0; li x2, 0; li x3, 0; li x4, 0; li x5, 0; li x6, 0;     \
        li x7, 0; li x8, 0; li x9, 0; li x10, 0; li x11, 0; li x12, 0;  \
        li x13, 0; li x14, 0; li x15, 0; li x16, 0; li x17, 0;          \
        li x18, 0; li x19, 0; li x20, 0; li x21, 0; li x22, 0;          \
        li x23, 0; li x24, 0; li x25, 0; li x26, 0; li x27, 0;          \
        li x28, 0; li x29, 0; li x30, 0; li x31, 0;                     \
        la t0, trap_vector;                                             \
        csrw mtvec, t0;                                                 \
        li t0, 0;                                                       \
        init;

#define RVTEST_CODE_END unimp

#define RVTEST_PASS li TESTNUM, 1; ecall

#define RVTEST_FAIL                                                     \
1:      beqz TESTNUM, 1b;                                               \
        slli TESTNUM, TESTNUM, 1;                                       \
        ori TESTNUM, TESTNUM, 1;                                        \
        ecall

#define RVTEST_DATA_BEGIN                                               \
        .pushsection .tohost, "aw", @progbits;                          \
        .balign 8; .globl tohost; tohost: .word 0, 0;                   \
        .popsection;                                                    \
        .balign 16;

#define RVTEST_DATA_END .balign 16;

#endif
