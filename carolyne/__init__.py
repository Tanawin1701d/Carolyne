# Carolyne — an ISA-agnostic out-of-order CPU generator built on Kathryn.
#
# Layout:
#   carolyne.isa   — description types and per-ISA packages
#                    (riscv, x86mini, ...)
#   carolyne.uarch — the generic OoO engine, elaborated from an IsaBase
#
# The ISA <-> microarchitecture boundary is specified in
# docs/design/uop_contract.md; it is a document, not a package.

__version__ = "0.1.0"
