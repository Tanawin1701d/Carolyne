# Decode tree: the ISA's mop table turned into what the decoder switches on.
# Pure description work, no Kathryn: Decode (decode.py) walks the result to
# build hardware, and the compile tool's verify decodes words with it.
#
# ONE µOP PER INSTRUCTION: every UopSeq holds exactly one µop. The sequences
# of one mop form a PREFIX TREE over their encoding fields: a shared first
# field is one switch, and a value that needs more bits is split by the next
# field. RV32IM's OP mop, for example:
#
#   MopTree(MOP_OP)                      guard: opcode [6:0] == 0110011
#   └─ DecodeSwitch funct3 [14:12]
#      ├─ 000 ─ DecodeSwitch funct7 [31:25]
#      │        ├─ 0000000 ─ DecodeLeaf ADD
#      │        ├─ 0100000 ─ DecodeLeaf SUB
#      │        └─ 0000001 ─ DecodeLeaf MUL
#      ├─ 001 ─ DecodeSwitch funct7 [31:25]
#      │        ├─ 0000000 ─ DecodeLeaf SLL
#      │        └─ 0000001 ─ DecodeLeaf MULH
#      ├─ ...
#      └─ 111 ─ DecodeSwitch funct7 [31:25]
#               ├─ 0000000 ─ DecodeLeaf AND
#               └─ 0000001 ─ DecodeLeaf REMU
#
# A mop whose sequences state no field is a single leaf (LUI, JAL):
#
#   MopTree(MOP_LUI)                     guard: opcode [6:0] == 0110111
#   └─ DecodeLeaf LUI
#
# build_decode_tree refuses what cannot be a prefix tree:
#
#   siblings switch on different fields     a sequence stops where a sibling goes on
#   ┌─ ADDI: funct3 = 000                   ┌─ ADD: funct3 = 000
#   └─ SUB : funct7 = 0100000   (refused)   └─ SUB: funct3 = 000, funct7 = 0100000  (refused)
#
# | part                  | what it is                                          |
# | --------------------- | --------------------------------------------------- |
# | `build_decode_tree`   | every mop as a MopTree (the hardware decoder's input) |
# | `mop_uops`            | the µops under a node, in tree order                |
# | `group_uops_by_level` | the flat (guard, µop) list the compile tool's verify uses |

from typing import NamedTuple, Tuple, Union

from carolyne.isa import IsaBase, Mop, Uop, UopSeq


# ---- the tree --------------------------------------------------------------------

class DecodeLeaf(NamedTuple):
    """The one µop a decode tree path ends in.

        DecodeLeaf(uop=SUB)        ─ SUB
    """
    uop : Uop


class DecodeSwitch(NamedTuple):
    """Pick a child by the value of one encoding field: word[end-1:start].

        DecodeSwitch(start=25, end=32,          ─ switch on word[31:25] (funct7)
                     cases=((0b0000000, ADD),     ├─ 0000000 ─ ADD
                            (0b0100000, SUB),     ├─ 0100000 ─ SUB
                            (0b0000001, MUL)))    └─ 0000001 ─ MUL

         31      25 24  20 19  15 14 12 11   7 6      0
        +----------+------+------+-----+------+--------+
        |  funct7  | rs2  | rs1  | f3  |  rd  | opcode |     the word
        +----------+------+------+-----+------+--------+
         ^^^^^^^^^^
         word[31:25]: start=25, end=32 (end is exclusive)
    """
    start : int
    end   : int
    cases : Tuple[Tuple[int, "DecodeNode"], ...]     # (field value, child)


DecodeNode = Union[DecodeLeaf, DecodeSwitch]


class MopTree(NamedTuple):
    """One mop: its own guard rule and the tree under it."""
    mop  : Mop
    root : DecodeNode


# one field test: ((start, end), value), the bits word[end-1:start] must equal value
FieldTest = Tuple[Tuple[int, int], int]


class DecodePath(NamedTuple):
    """One sequence on its way down the tree: the field tests still to make,
    and the µop it ends in. Each level of the tree uses up the first test.

        SUB on its way down RV32IM's OP tree:

        where                       tests left                                uop
        under zif(opcode == OP)     (((12,15), 000), ((25,32), 0100000))      SUB
          └─ case funct3 = 000      (((25,32), 0100000),)                     SUB
               └─ case funct7 =     ()                                        SUB
                  0100000           no tests left: this path is DecodeLeaf SUB
    """
    tests : Tuple[FieldTest, ...]
    uop   : Uop


def seq_field_tests(uop_seq: UopSeq) -> Tuple[FieldTest, ...]:
    """The field tests a sequence states, in order: what the tree switches on.

        SUB:  matcher_field = funct3 | funct7 = ((12, 15), (25, 32))
              matcher_value = (0b000, 0b0100000)
          ->  (((12, 15), 0b000), ((25, 32), 0b0100000))
              first switch on funct3, then on funct7

        LUI:  no matcher  ->  ()      the mop's opcode alone names it
    """
    if uop_seq.matcher_value is None:
        return ()
    return tuple(zip(uop_seq.matcher_field.match_idx, uop_seq.matcher_value.match_value))


def build_decode_tree(isa: IsaBase) -> Tuple[MopTree, ...]:
    """Every mop as a tree over its sequences' encoding fields.

    - refuses a sequence of more than one µop: this decoder emits one µop
      per instruction
    - refuses a tree that is not a prefix tree: siblings that switch on
      different fields, or one sequence that stops where a sibling goes on
    """
    trees = []
    for mop in isa.mops:
        if mop.matcher_value is None:
            raise ValueError(f"ISA '{isa.name}': a mop on field '{mop.matcher_field.name}' "
                             f"states no value, so nothing tells its encoding apart")
        paths = []
        for uop_seq in mop.uop_seq:
            if len(uop_seq.uops) != 1:
                raise ValueError(
                    f"ISA '{isa.name}': the sequence starting at µop '{uop_seq.uops[0].name}' "
                    f"has {len(uop_seq.uops)} µops; this decoder emits one µop per instruction")
            tests = seq_field_tests(uop_seq)
            uop   = uop_seq.uops[0]
            paths.append(DecodePath(tests, uop))
        root = _build_node(isa, paths)
        trees.append(MopTree(mop, root))
    return tuple(trees)


def _build_node(isa: IsaBase, paths: list) -> DecodeNode:
    """The subtree for `paths`: each path's first test picks its branch, the
    rest of its tests go down with it.

    One level of the walk, for the funct3 = 000 group of RV32IM's OP:

        paths in (tests, uop)                        node out
        (((25,32), 0000000),) ADD  ┐
        (((25,32), 0100000),) SUB  ├─ same field ─   DecodeSwitch(25, 32)
        (((25,32), 0000001),) MUL  ┘                 ├─ 0000000: [((), ADD)] ─ DecodeLeaf ADD
                                                     ├─ 0100000: [((), SUB)] ─ DecodeLeaf SUB
                                                     └─ 0000001: [((), MUL)] ─ DecodeLeaf MUL
    """
    if len(paths) == 1 and not paths[0].tests:
        return DecodeLeaf(paths[0].uop)

    names = ", ".join(path.uop.name for path in paths)
    if any(not path.tests for path in paths):
        raise ValueError(f"ISA '{isa.name}': µops {names} cannot be told apart: one "
                         f"of them states no further field where a sibling does")
    fields = {path.tests[0][0] for path in paths}
    if len(fields) != 1:
        raise ValueError(f"ISA '{isa.name}': µops {names} switch on different fields "
                         f"{sorted(fields)}; one decode case needs one field")

    # group by the value of the shared first field; each group keeps its remaining tests
    # group the paths by the value of the shared first field, and drop that
    # test from each: at the root of RV32IM's OP (field funct3 = (12, 15))
    #
    #   path in                                           by_value
    #   ((f3, 000), (f7, 0000000)) ADD   ─┐
    #   ((f3, 000), (f7, 0100000)) SUB   ─┼─ 000  ─>  [((f7, 0000000),) ADD,
    #   ((f3, 000), (f7, 0000001)) MUL   ─┘            ((f7, 0100000),) SUB,
    #                                                  ((f7, 0000001),) MUL]
    #   ((f3, 001), (f7, 0000000)) SLL   ─┬─ 001  ─>  [((f7, 0000000),) SLL,
    #   ((f3, 001), (f7, 0000001)) MULH  ─┘            ((f7, 0000001),) MULH]
    #   ...
    (start, end), = fields
    by_value = {}
    for path in paths:
        (_field, value), *rest = path.tests
        child_path = DecodePath(tuple(rest), path.uop)
        if value not in by_value:
            by_value[value] = []
        by_value[value].append(child_path)

    # one case per value, its subtree built from the paths that took it
    #
    #   by_value                                    cases
    #   000 ─ [(f7 tests) ADD, SUB, MUL]   ─>  (000, DecodeSwitch f7 ─ ADD, SUB, MUL)
    #   001 ─ [(f7 tests) SLL, MULH]       ─>  (001, DecodeSwitch f7 ─ SLL, MULH)
    #   ...
    #   returned:  DecodeSwitch(12, 15, cases)     the switch on funct3
    cases = []
    for value, child_paths in by_value.items():
        child = _build_node(isa, child_paths)
        cases.append((value, child))
    return DecodeSwitch(start, end, tuple(cases))


def mop_uops(node: DecodeNode) -> Tuple[Uop, ...]:
    """Every µop under `node`, in tree order."""
    if isinstance(node, DecodeLeaf):
        return (node.uop,)
    return tuple(uop for _value, child in node.cases for uop in mop_uops(child))


# ---- the flat form, for the compile tool's verify -------------------------------------

def _collect_matchers(mop: Mop, uop_seq: UopSeq) -> tuple:
    """Every stated (field, value) rule of one (mop, uop_seq): its guard.

    - the mop's rule, then the uop_seq's: the whole encoding side; a µop
      template carries no matcher
    - a half-stated matcher (field, no value) tests nothing and is dropped
    """
    pairs = [(mop.matcher_field,     mop.matcher_value),
             (uop_seq.matcher_field, uop_seq.matcher_value)]

    # a stated value always has its field (check_matcher_pair, at
    # construction), so value alone decides
    return tuple((field, value) for field, value in pairs if value is not None)


def group_uops_by_level(isa: IsaBase) -> tuple:
    """The mop table flattened into (guard, µop) pairs, one list per level.

    - one guard per (mop, uop_seq): EVERY stated rule on it, the SAME
      conjunction at every level, so the identity cannot change mid-crack
    - a (mop, uop_seq) with no rule at all is refused: nothing tells it apart
    - levels[k] = ((matchers, uop), ...) for every uop_seq longer than k;
      len(levels) = the ISA's longest crack (1 while one µop is locked)

        levels[0] = (((opcode, 0110011), (funct3_7, (000, 0000000))), ADD),
                    (((opcode, 0110011), (funct3_7, (000, 0100000))), SUB),
                    ...
    """
    # step 1: per (mop, uop_seq), its guard rules and its µops
    guarded_seqs = []
    for mop in isa.mops:
        for uop_seq in mop.uop_seq:
            matchers = _collect_matchers(mop, uop_seq)
            if not matchers:
                raise ValueError(
                    f"ISA '{isa.name}': the crack starting at µop "
                    f"'{uop_seq.uops[0].name}' has no (field, value) rule "
                    f"at all, so nothing tells its encoding from its "
                    f"neighbours'")
            guarded_seqs.append((matchers, uop_seq.uops))

    # step 2: group by level, levels[k] = the k-th µop of every longer crack
    n_levels = max(len(uops) for _matchers, uops in guarded_seqs)
    levels   = []
    for level in range(n_levels):
        alive = tuple((matchers, uops[level])
                      for matchers, uops in guarded_seqs
                      if len(uops) > level)
        levels.append(alive)
    return tuple(levels)
