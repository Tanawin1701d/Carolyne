# Code style

The formatting and comment rules this repo is written to. CLAUDE.md §7 makes
them binding at WRITE time, for every file, not only on request.

**This is a vendored copy.** The live version Claude Code loads is
`~/.claude/skills/codestyle-skill/SKILL.md`, and that one is authoritative.
This copy exists so the rules travel with the repository — readable by anyone
who does not have the skill installed, and reviewable in a diff. If the two
disagree, the skill wins; update it first, then re-copy.

The worked pattern for rule 7 (comments) is `example_comment.py` at the repo
root: eight sections, each showing GOOD against BAD.

---

Apply the owner's personal formatting conventions to the target code.
Do NOT change logic, rename identifiers for semantic reasons, or refactor —
layout and formatting only, unless the user asks for more. (Rule 9 is the
one exception: on reformatting, FLAG naming violations rather than renaming;
apply it fully only when writing new code.)

---

## Core rules

### 1. Column-align `:` in struct/class fields and function parameters

Pad names with spaces so the `:` (or `=`, or type annotation) lines up in a vertical column.

```rust
// Rust struct fields
ident_base       : IdentBase,
hw_type          : HwComponentType,
master_module_i  : ModuleIdent,

// Rust / Python / any multi-param function signature
pub fn build_io_wire(
    arena      : &mut ModelArena,
    src_module : ModuleIdent,
    src_signal : HcpIdent,
    is_input   : bool,
) -> HcpIdent
```

```python
# Python
def build_io_wire(
    arena      : ModelArena,
    src_module : ModuleIdent,
    src_signal : HcpIdent,
    is_input   : bool,
) -> HcpIdent:
```

```cpp
// C++
void buildIoWire(
    ModelArena* arena     ,
    ModuleIdent srcModule ,
    HcpIdent    srcSignal ,
    bool        isInput
);
```

Grouped assignments align the `=`; dict literals align the `:`.

```python
self.config    = config
self.rsv_spec  = rsv_spec
self.exec_unit = rsv_spec.exec_unit[0]

promised_fields = {"rob_des_idx": free_idx[lane],
                   "is_spec"    : is_spec,
                   "spec_tag"   : tag}
```

### 2. Collapse trivial getters / one-liner methods to a single line

If the entire body fits in one line, keep it there. Column-align the return types and bodies across a group of related getters.

```rust
pub fn get_ident_base    (&self)     -> &IdentBase     { &self.ident_base }
pub fn get_ident_base_mut(&mut self) -> &mut IdentBase { &mut self.ident_base }
pub fn get_hw_type       (&self)     -> HwComponentType { self.hw_type }
```

```python
def get_name(self)  -> str:  return self._name
def get_id  (self)  -> int:  return self._id
def get_type(self)  -> Type: return self._type
```

### 3. Section separator comments

Use dashed-line comments to divide logical groups inside a file or class.
Short sections use inline dashes; long files use full-width blocks.

```
// ---- Reg ----------------------------------------------------------------
// ---- Wire ---------------------------------------------------------------

// -----------------------------------------------------------------------
// HCP factories
// -----------------------------------------------------------------------
```

Adapt the comment syntax to the language (`#`, `//`, `--`, `/* */` etc.).

### 4. match / switch arms: align the `=>`/ `:` / `->` operator

```rust
Self::Reg               => "REG",
Self::StateReg          => "SR_ST",
Self::CondWaitStateReg  => "SR_CDWT",
```

```python
match hw_type:
    case HwType.REG              : return "REG"
    case HwType.STATE_REG        : return "SR_ST"
    case HwType.COND_WAIT_STATE  : return "SR_CDWT"
```

### 5. Multi-line function signature: one param per line, closing delimiter on its own line

Trigger: 3 or more parameters, OR any parameter list that would exceed ~90 chars.

```rust
pub fn find_common_ancestor(
    arena : &ModelArena,
    a     : ModuleIdent,
    b     : ModuleIdent,
) -> (Vec<ModuleIdent>, Vec<ModuleIdent>)
```

Always include trailing comma on the last parameter (where the language allows it).

### 6. Casing conventions (apply per language)

| Concept            | Rust            | Python          | C++             | Java/Kotlin     |
|--------------------|-----------------|-----------------|-----------------|-----------------|
| Types / classes    | `PascalCase`    | `PascalCase`    | `PascalCase`    | `PascalCase`    |
| Functions/methods  | `snake_case`    | `snake_case`    | `camelCase`     | `camelCase`     |
| Variables/fields   | `snake_case`    | `snake_case`    | `camelCase`     | `camelCase`     |
| Constants          | `SCREAMING_SNAKE` | `SCREAMING_SNAKE` | `SCREAMING_SNAKE` | `SCREAMING_SNAKE` |
| Ident handle vars  | `name_i` suffix | `name_i` suffix | `nameI` suffix  | `nameI` suffix  |

The `_i` / `I` suffix marks lightweight handle/ident variables (not the object itself).

### 7. Comments: scannable, sized to the code, plain

**Shape**

- Docstrings: ONE summary line, then short `-` bullets — never paragraphs.
- A bullet states a rule the reader would break without it (WHY, not WHAT).
- Emphasis words in CAPS mark important facts: `LIMIT:` for known
  incompleteness, `TODO:` for planned work (greppable), `NOT here:` for
  deliberate absences. A marker follows the same rule as a bullet: it goes in
  because the next reader would waste time without it, not to show the author
  thought about it.
- No history in source — what was tried/reverted and cost/benefit prose
  belongs in the project design log (CLAUDE.md), not comments.
- Module header: what the module IS plus the one or two rules a reader
  must know; a table of parts if the module has several.
- `///` or language-equivalent for public API docs; `//` for inline notes.

**Size — THE DOC IS NEVER LONGER THAN THE BODY IT DESCRIBES**

```
body          doc
1-2 lines     the name alone, or one line if it is not obvious
3-8 lines     one line; add ONE bullet only if a rule outside the file applies
longer        summary + bullets, one per rule, still no paragraph
```

If the bullets outnumber the statements, the doc is wrong. Either cut it, or
the function is doing too much.

ONE EXCEPTION: an abstract or interface method whose body is a stub. There the
docstring IS the deliverable — it is the contract someone writes an
implementation against — so the size rule does not apply.

When a short body still needs an outside rule stated, put it in a trailing
inline note beside the line, not in the docstring.

**Inline comments — both halves**

- Never restate a line that reads itself.
- But DO annotate what does not: a long stretch, a dense expression, or code
  whose reason is outside the file. Exactly ONE line — trailing if it fits the
  margin, on a dedicated line above when it covers a block.
- One line, not two. If it needs a paragraph, the code needs a helper with a
  name instead.

**Plain language — write for a reader whose first language is not English**

- Use the common word, not the clever one.
- One idea per sentence. Do not chain clauses with dashes.
- No metaphors, and never describe code as if it were a person.
- Domain terms are KEPT (µop, rename, mutex, arena, writeback): those are
  exact. It is ordinary English that must be plain.

```
instead of                     write
the value RIDES with the µop   the value is stored in the µop record
a temp LIVES in one block      a temp exists only inside one block
the station OWNS its policy    the station decides its policy
a level HANDS a bubble         a level outputs an empty entry
an operand REACHES a RegFile   an operand refers to a RegFile
the core SPEAKS uop_idx        the core uses uop_idx
the BARGAIN this type makes    the rule this type follows
the DISCIPLINE the layer runs on   the rule the layer uses
it BITES at issue              it causes a bug at issue
a LOAD-BEARING fact            an important fact
the cost COMES DUE later       the cost appears when X is added
where the field SITS           where the field is
```

### 8. Parallel method calls: align the dot

When consecutive lines make the same kind of call on sibling objects, pad
the receiver so the `.` forms a column — the group reads as one table.

```python
self.fetch   .connect(self.decode)
self.decode  .connect(self.fetch, self.dispatch)
self.dispatch.connect(self.decode, self.backend_meta, ...)
```

### 9. Names state the fact they hold

On reformatting, FLAG violations rather than renaming; apply fully when
writing new code.

- A variable is named for the TYPE or FACT it holds, never a metaphor:
  `atm_opr` not `core`, `dispatch_bus` not `dispatch`, `dec_opr_valid`
  not `in_hand`.
- A cache of a method's answers takes that method's name
  (`_lane_targets_me` caches `lane_targets_me(...)`).
- Singular for ONE record/array whose rows are the plurality
  (`dispatch_bus[lane]`); plural only for a Python collection of separate
  objects (`rsvs`, `exus`, `stage_metas`).
- Helpers are verb-first (`read_row_fields`, `drive_by_uop`, `uop_hit`).
- Related files share a prefix so they sort together (`exec_unit.py`,
  `exec_unit_alu.py`, `exec_unit_br.py`, `exec_unit_util.py`).

---

## Workflow

1. Read the target file or block.
2. Identify the language.
3. Apply rules 1–6 and 8 in order — layout only, no logic changes. Rule 9:
   flag only (rename nothing unless the user asks). Rule 7 changes CONTENT,
   not layout: apply it when writing new code, or on a deliberate comment
   pass the user asked for — not as part of a reformat.
4. If column-alignment would require re-padding more than ~20 lines due to one long name, flag it and ask whether to proceed or skip that group.
5. Show a diff or the reformatted block. Do not silently overwrite unless the user said so.
