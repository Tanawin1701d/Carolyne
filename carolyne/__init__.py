# Carolyne — an ISA-agnostic out-of-order CPU generator built on Kathryn.
#
# Layout:
#   carolyne.contract — the µop contract: the ISA <-> microarchitecture boundary
#                       (see docs/design/uop_contract.md, the normative spec)
#   carolyne.isa      — per-ISA description packages (riscv, x86mini, ...)
#   carolyne.uarch    — the generic OoO engine, elaborated from an IsaBase

__version__ = "0.1.0"
