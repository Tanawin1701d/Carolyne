# common_field is the ONE place an O3 record field is named. Constants close
# the gap for every string-keyed write; they cannot close it for a Karray
# CLASS BODY, where the attribute name IS the field name and no constant can
# stand in. These tests are what closes that half: they hold each declaration
# to the constant that names it, so a typo in either one fails here.

import ast
import pathlib

import pytest

from carolyne.uarch.o3 import common_field as CF

O3 = pathlib.Path(CF.__file__).parent


def _declared_fields(module: str, cls: str) -> set:
    """The kaf() field names a Karray class body declares, read off the source.

    - the source, not the class: a declared field is an attribute assignment,
      and importing would need a config to size it
    """
    tree = ast.parse((O3/module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {t.id for s in node.body if isinstance(s, ast.Assign)
                    for t in s.targets if isinstance(t, ast.Name)}
    raise AssertionError(f"{module}: no class {cls}")


# (module, class, the constants its body must declare)
RECORDS = [
    ("fetch_helper.py",    "FetchEntryBase",   [CF.PC, CF.INSTR]),
    ("decode_helper.py",   "DecodeEntryBase",  [CF.VALID, CF.PC, CF.NPC, CF.UOP_IDX,
                                                CF.IS_BRANCH, CF.IS_STORE, CF.RSV_ID]),
    ("dispatch_helper.py", "DispatchEntryBase",[CF.VALID, CF.PC, CF.NPC, CF.UOP_IDX,
                                                CF.IS_BRANCH, CF.IS_STORE, CF.RSV_ID,
                                                CF.IS_SPEC, CF.SPEC_TAG, CF.ROB_DES_IDX]),
    ("rsv_helper.py",      "RsvEntryBase",     [CF.VALID, CF.IS_SPEC, CF.SPEC_TAG,
                                                CF.UOP_IDX, CF.ROB_DES_IDX]),
    ("rsv_helper.py",      "RsvO3Entry",       [CF.IS_LOWER_TRACK, CF.TRACK]),
    ("rob_helper.py",      "RobEntry",         [CF.WB_FIN, CF.IS_BRANCH,
                                                CF.IS_STORE, CF.PC]),
    ("store_buf.py",       "StBufEntry",       [CF.BUSY, CF.COMPLETE, CF.IS_SPEC,
                                                CF.SPEC_TAG, CF.MEM_ADDR, CF.DATA]),
    ("prf.py",             "PrfEntry",         [CF.FIN, CF.DATA]),
    ("rt.py",              "RtEntry",          [CF.RENAMED, CF.PRF_IDX]),
    ("common_field.py",    "SpecLane",         [CF.IS_SPEC, CF.SPEC_TAG]),
]


@pytest.mark.parametrize("module,cls,names", RECORDS,
                         ids=[f"{c}" for _m, c, _n in RECORDS])
def test_a_record_declares_the_fields_its_constants_name(module, cls, names):
    # The half a constant cannot reach: a class body spells the literal, so
    # this is what catches a declaration and a write drifting apart.
    missing = [n for n in names if n not in _declared_fields(module, cls)]
    assert not missing, f"{cls} declares no {missing}"


def test_no_o3_module_names_a_field_with_a_literal():
    """No field name is spelled ANYWHERE in o3: every one is a constant.

    Stronger than checking known names: a literal is refused whatever it says,
    so a MISSPELLING fails here too. That is the point — a constant catches a
    typo only if the typo is in the constant's name, where Python catches it.

    - checked where a string MEANS a field: a dict key, or a `[...]` subscript
    - a Karray class body declares by attribute, not by string, so it does not
      appear here; the test above is what holds those to the constants
    - a signal name that reads the same (fetch's `reg(w, "pc")`) is a
      different thing and is not a dict key, so it is left alone
    """
    offenders = []
    for f in sorted(O3.glob("*.py")):
        if f.name == "common_field.py":
            continue                                    # the definitions
        for node in ast.walk(ast.parse(f.read_text())):
            lits = []
            if isinstance(node, ast.Dict):
                lits = [k for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            elif (isinstance(node, ast.Subscript)
                  and isinstance(node.slice, ast.Constant)
                  and isinstance(node.slice.value, str)):
                lits = [node.slice]
            offenders += [f"{f.name}:{k.lineno} {k.value!r}" for k in lits]
    assert not offenders, ("field names must come from common_field, not a "
                           "literal: " + ", ".join(offenders))
