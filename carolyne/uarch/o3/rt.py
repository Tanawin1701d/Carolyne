from kathryn import *
from kathryn.signal import to_ref

from carolyne.isa import RegFile
from carolyne.uarch.common.karray_util import OH
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.priority import PRI_COMMIT, PRI_MIS_PRED, PRI_RENAME


def write_entry(dst_row, dyn_idx, amount, **fields):
    """Write the one element of a WIRE row that `dyn_idx` names, at run time.

    A runtime-indexed Karray write needs a REG backing -- a wire cannot hold its
    non-selected elements -- so on a wire the selection moves into the guard:
    one statically-indexed write per entry, enabled when the index names it.
    That is the same hardware a dynamic write would build, spelled the way
    Kathryn accepts. The caller's own `zif` (if any) still wraps this one.
    """
    for arch_idx in range(amount):
        with zif(dyn_idx == arch_idx):
            dst_row[arch_idx] *= fields


def copy_row(dst_row, src_row, amount, clocked):
    """Copy one whole row of a Karray, element by element.

    A Karray selection collapses EVERY dimension to exactly one element -- there
    are no ranges, so `dst_row *= src_row` is not a statement Kathryn has. The
    loop is the spelling of it. `clocked` picks the operator the destination
    needs: `|=` for a reg-backed array, `*=` for a wire-backed one.
    """
    for arch_idx in range(amount):
        if clocked:
            dst_row[arch_idx] |= src_row[arch_idx]
        else:
            dst_row[arch_idx] *= src_row[arch_idx]

class RtEntry(Karray):
    renamed = kaf(1)
    prf_idx = kaf()


class Rt(Module):
    # mispredict | commit + rename

    def __init__(self,
                 config      : CPUO3_Config,
                 isa_reg_file: RegFile,
                 amt_prf     : int,
                 rename_ports: int,
                 commit_port : int):

        self.config       = config
        self.isa_reg_file =  isa_reg_file
        self.amt_prf      =  amt_prf
        self.rename_ports =  rename_ports
        self.commit_port  =  commit_port

        super().__init__()


    @init
    def com_declare(self):

        self.prf_idx_width = (self.amt_prf-1).bit_length()

        self.master_rt = RtEntry(
            HwComponentType.REG,
            (1, self.isa_reg_file.amount),
            "master_rt",
            prf_idx =  self.prf_idx_width
        )

        self.spec_rt = RtEntry(
            HwComponentType.REG,
            (self.config.sptag_len, self.isa_reg_file.amount),
            "master_spec",
            prf_idx = self.prf_idx_width
        )

        self.temp_commit = RtEntry(
            HwComponentType.WIRE,
            (1, self.isa_reg_file.amount),
            "temp_commit",
            prf_idx=self.prf_idx_width

        )

        self.temp_dispatch = RtEntry(
            HwComponentType.WIRE,
            (self.rename_ports, self.isa_reg_file.amount),
            "temp_dispatch",
            prf_idx =  self.prf_idx_width
        )

        #list of (req_rename_sig, is_branch_sig, spectag_dyn, arch_idx_to_set, prf_idx_to_set)
        # index correspond to self.rename_ports
        self.rename_metas: list[tuple | None] = [None for _ in range(self.rename_ports)]



    @flow
    def on_normal_flow(self):
        # do update master every cycle

        amount = self.isa_reg_file.amount

        # The stage chain: the committed state, then one row per RENAME PORT,
        # each lane seeing what the lane before it left. The loop is bounded by
        # the rows temp_dispatch HAS — it is (rename_ports, amount) — and the
        # row that goes back to master is the last lane's, not the commit row.
        copy_row(self.temp_commit[0],   self.master_rt[0],  amount, clocked=False)
        copy_row(self.temp_dispatch[0], self.temp_commit[0], amount, clocked=False)
        for i in range(1, self.rename_ports):
            copy_row(self.temp_dispatch[i], self.temp_dispatch[i-1], amount, clocked=False)

        copy_row(self.master_rt[0], self.temp_dispatch[self.rename_ports - 1],
                 amount, clocked=True)

    def read_rename(self, port_idx: int, arch_dyn_idx):
        """(renamed, prf_idx) of one architectural register, as rename port
        `port_idx` sees it: the state AFTER every earlier lane's rename of
        this cycle and BEFORE its own.

        - port 0 reads the commit row (the master's wire alias, plus this
          cycle's commit fixups); port k reads the row lane k-1 overlaid —
          on_normal_flow's chain
        - a read only, so it works on the wire rows; the overlays it sees
          are whatever fired this cycle
        """
        row = (self.temp_commit[0] if port_idx == 0
               else self.temp_dispatch[port_idx - 1])
        entry = row[arch_dyn_idx]
        return to_ref(entry.renamed), to_ref(entry.prf_idx)

    # last_valid_spec_tag is dynamic
    def on_mis_pred(self, last_valid_spec_tag_dyn):

        with priority(PRI_MIS_PRED):
            copy_row(self.master_rt[0], self.spec_rt[OH(last_valid_spec_tag_dyn)],
                     self.isa_reg_file.amount, clocked=True)



    def on_commit(self, arch_dyn_idx, prf_dyn_idx):

        with priority(PRI_COMMIT):
            with zif(to_ref(self.master_rt[0][arch_dyn_idx].renamed).land(
                     to_ref(self.master_rt[0][arch_dyn_idx].prf_idx) == prf_dyn_idx
                     )):
                write_entry(self.temp_commit[0], arch_dyn_idx,
                            self.isa_reg_file.amount, prf_idx=prf_dyn_idx)

            for i in range(self.config.sptag_len):
                with zif(to_ref(self.spec_rt[0][arch_dyn_idx].renamed).land(
                         to_ref(self.spec_rt[0][arch_dyn_idx].prf_idx) == prf_dyn_idx
                         )):
                    self.spec_rt[0][arch_dyn_idx].prf_idx |= prf_dyn_idx

    def book_rename(self, port_idx: int, req_rename_sig, is_branch_sig, spectag_dyn, arch_idx_to_set, prf_idx_to_set):
        self.rename_metas[port_idx] = (req_rename_sig, is_branch_sig, spectag_dyn, arch_idx_to_set, prf_idx_to_set)

    def on_rename(self):
        """Overlay each port's registered rename on the stage chain.

        - call in the granted scope: the overlays and the branch snapshots
          take the grant as their gate there
        - lane k writes ITS OWN temp_dispatch row, so every later lane sees
          it through the chain and master takes the last row
        - a branch snapshots temp_dispatch[k] AFTER its own overlay resolves
          (PRI_RENAME beats the chain copy): the state it leaves behind,
          which is what on_mis_pred restores — the branch itself retires,
          so its own rename must survive the rollback
        """
        amount = self.isa_reg_file.amount
        with priority(PRI_RENAME):
            for port_idx, metas in enumerate(self.rename_metas):
                if metas is None:
                    raise ValueError(
                        f"Rt of '{self.isa_reg_file.name}': rename port "
                        f"{port_idx} has no booking — call book_rename for "
                        f"every port before on_rename")
                req_rename_sig, is_branch_sig, spectag_dyn, \
                    arch_idx_to_set, prf_idx_to_set = metas
                with zif(req_rename_sig):
                    write_entry(self.temp_dispatch[port_idx], arch_idx_to_set,
                                amount, renamed=1, prf_idx=prf_idx_to_set)
                with zif(req_rename_sig & is_branch_sig):
                    copy_row(self.spec_rt[OH(spectag_dyn)],
                             self.temp_dispatch[port_idx],
                             amount, clocked=True)
