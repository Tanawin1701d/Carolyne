# The MIPS32 mop table flattened for decode's walk, evaluated in PURE PYTHON
# on hand-built encodings: every instruction picks exactly one µop, and the
# encodings the description leaves out pick none.

from carolyne.isa.mips import Mips32, uop as U
from carolyne.uarch.o3.decode import group_uops_by_level

ISA    = Mips32()
LEVELS = group_uops_by_level(ISA)


def _hits(word: int, level: int = 0) -> list:
    """Every µop whose rules hold for this instruction word, at one level."""
    return [uop for matchers, uop in LEVELS[level]
            if all(((word >> start) & ((1 << (end - start)) - 1)) == want
                   for field, value in matchers
                   for (start, end), want in zip(field.match_idx, value.match_value))]


def _r(funct, rs=0, rt=0, rd=0, sa=0, opcode=0) -> int:
    return opcode << 26 | rs << 21 | rt << 16 | rd << 11 | sa << 6 | funct


def _i(opcode, rs=0, rt=0, imm=0) -> int:
    return opcode << 26 | rs << 21 | rt << 16 | (imm & 0xFFFF)


def _j(opcode, index=0) -> int:
    return opcode << 26 | (index & 0x3FFFFFF)


SPECIAL2, SPECIAL3 = 28, 31


def test_every_encoding_picks_exactly_one_uop():
    cases = {
        "nop"               : (0x00000000,                                   U.UOP_SLL),
        "sll $1,$2,3"       : (_r(0,  rt=2, rd=1, sa=3),                     U.UOP_SLL),
        "srl $1,$2,3"       : (_r(2,  rt=2, rd=1, sa=3),                     U.UOP_SRL),
        "rotr $1,$2,3"      : (_r(2,  rs=1, rt=2, rd=1, sa=3),               U.UOP_ROTR),
        "srlv $1,$2,$3"     : (_r(6,  rs=3, rt=2, rd=1),                     U.UOP_SRLV),
        "rotrv $1,$2,$3"    : (_r(6,  rs=3, rt=2, rd=1, sa=1),               U.UOP_ROTRV),
        "sra $1,$2,3"       : (_r(3,  rt=2, rd=1, sa=3),                     U.UOP_SRA),
        "jr $31"            : (_r(8,  rs=31),                                U.UOP_JR),
        "jalr $31,$2"       : (_r(9,  rs=2, rd=31),                          U.UOP_JALR),
        "movn $1,$2,$3"     : (_r(11, rs=2, rt=3, rd=1),                     U.UOP_MOVN),
        "mfhi $1"           : (_r(16, rd=1),                                 U.UOP_MFHI),
        "mtlo $2"           : (_r(19, rs=2),                                 U.UOP_MTLO),
        "mult $1,$2"        : (_r(24, rs=1, rt=2),                           U.UOP_MULT),
        "divu $1,$2"        : (_r(27, rs=1, rt=2),                           U.UOP_DIVU),
        "addu $1,$2,$3"     : (_r(33, rs=2, rt=3, rd=1),                     U.UOP_ADDU),
        "nor $1,$2,$3"      : (_r(39, rs=2, rt=3, rd=1),                     U.UOP_NOR),
        "sltu $1,$2,$3"     : (_r(43, rs=2, rt=3, rd=1),                     U.UOP_SLTU),
        "bltz $1,off"       : (_i(1, rs=1, rt=0,  imm=-4 >> 2),              U.UOP_BLTZ),
        "bgezal $1,off"     : (_i(1, rs=1, rt=17, imm=8 >> 2),               U.UOP_BGEZAL),
        "j target"          : (_j(2, 0x100),                                 U.UOP_J),
        "jal target"        : (_j(3, 0x100),                                 U.UOP_JAL),
        "beq $1,$2,off"     : (_i(4, rs=1, rt=2, imm=3),                     U.UOP_BEQ),
        "bgtz $1,off"       : (_i(7, rs=1, imm=3),                           U.UOP_BGTZ),
        "addiu $1,$2,-1"    : (_i(9, rs=2, rt=1, imm=-1),                    U.UOP_ADDIU),
        "sltiu $1,$2,5"     : (_i(11, rs=2, rt=1, imm=5),                    U.UOP_SLTIU),
        "ori $1,$2,0xff"    : (_i(13, rs=2, rt=1, imm=0xFF),                 U.UOP_ORI),
        "lui $1,0x1000"     : (_i(15, rt=1, imm=0x1000),                     U.UOP_LUI),
        "mul $1,$2,$3"      : (_r(2,  rs=2, rt=3, rd=1, opcode=SPECIAL2),    U.UOP_MUL),
        "clz $1,$2"         : (_r(32, rs=2, rt=1, rd=1, opcode=SPECIAL2),    U.UOP_CLZ),
        "ext $1,$2,3,4"     : (_r(0,  rs=2, rt=1, rd=3, sa=3, opcode=SPECIAL3), U.UOP_EXT),
        "ins $1,$2,3,4"     : (_r(4,  rs=2, rt=1, rd=6, sa=3, opcode=SPECIAL3), U.UOP_INS),
        "seb $1,$2"         : (_r(32, rt=2, rd=1, sa=16, opcode=SPECIAL3),   U.UOP_SEB),
        "seh $1,$2"         : (_r(32, rt=2, rd=1, sa=24, opcode=SPECIAL3),   U.UOP_SEH),
        "lw $1,4($2)"       : (_i(35, rs=2, rt=1, imm=4),                    U.UOP_LW),
        "lbu $1,4($2)"      : (_i(36, rs=2, rt=1, imm=4),                    U.UOP_LBU),
        "sw $1,4($2)"       : (_i(43, rs=2, rt=1, imm=4),                    U.UOP_SW),
        "sh $1,2($2)"       : (_i(41, rs=2, rt=1, imm=2),                    U.UOP_SH),
    }
    for asm, (word, want) in cases.items():
        picked = _hits(word)
        assert len(picked) == 1, f"{asm}: {[u.name for u in picked]}"
        assert picked[0] is want, asm


def test_what_the_description_leaves_out_matches_nothing():
    # A no-hit lane keeps write_lane_default's valid=0: the machine decodes
    # these into nothing, and the build's verify step reports them.
    assert _hits(_r(12))                          == []   # syscall
    assert _hits(_r(13))                          == []   # break
    assert _hits(_r(15))                          == []   # sync
    assert _hits(_r(52, rs=1, rt=2))              == []   # teq
    assert _hits(_r(0, rs=1, rt=2, opcode=SPECIAL2)) == []   # madd
    assert _hits(_r(32, rt=2, rd=1, sa=2, opcode=SPECIAL3)) == []   # wsbh
    assert _hits(_i(16))                          == []   # COP0
    assert _hits(_i(20, rs=1, rt=2))              == []   # beql
    assert _hits(_i(34, rs=2, rt=1))              == []   # lwl
    assert _hits(_i(1, rs=1, rt=2))               == []   # bltzl (REGIMM 2)
    assert _hits(_r(2, rs=2, rt=2, rd=1))         == []   # srl with a reserved rs field


def test_mips32_reaches_every_uop_in_one_level():
    assert len(LEVELS) == 1
    reached = [uop for _matchers, uop in LEVELS[0]]
    assert len(reached) == len(ISA.uops) == 63
    assert {id(u) for u in reached} == {id(u) for u in ISA.uops}
    assert sorted(u.uop_idx for u in reached) == list(range(63))


def test_a_uop_carries_every_rule_on_its_path():
    by_name = {uop.name: matchers for matchers, uop in LEVELS[0]}
    assert {f.name for f, _v in by_name["ROTR"]} == {"opcode", "funct+rs"}
    assert {f.name for f, _v in by_name["SEB"]}  == {"opcode", "funct+sa"}
    assert {f.name for f, _v in by_name["BGEZ"]} == {"opcode", "rt"}
    assert [f.name for f, _v in by_name["LW"]]   == ["opcode"]
