from kathryn import *
from kathryn.signal import to_ref

from carolyne.isa import RegFile
from carolyne.uarch.o3.config import CPUO3_Config


PRI_MIS_PRED = DEFAULT_UE_PRI_USER + 5
PRI_RENAME   = DEFAULT_UE_PRI_USER + 4
PRI_COMMIT   = DEFAULT_UE_PRI_USER + 3


def OH(one_hot_sig):
    """Index a Karray dimension with a ONE-HOT signal.

    Kathryn's callable index splits by DIRECTION. On a write destination it is
    called once per index and returns that element's 1-bit enable; on a read
    source the dimension folds through a reduce tree and the callable is a 2:1
    select, picking the side whose covered indices hold the hot bit. One object
    serves both, dispatching on how many arguments Kathryn hands it.
    """
    def index(*args):
        if len(args) == 1:                          # write: fn(i) -> enable bit
            return one_hot_sig[args[0]]
        left, _right, _level = args                 # read : fn(a, b, level) -> pick-left
        return any_of([one_hot_sig[i] for i in left.indices])
    return index


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

        copy_row(self.temp_commit[0],   self.master_rt[0],  amount, clocked=False)
        copy_row(self.temp_dispatch[0], self.temp_commit[0], amount, clocked=False)
        for i in range(1, self.config.sptag_len):
            copy_row(self.temp_dispatch[i], self.temp_dispatch[i-1], amount, clocked=False)

        copy_row(self.master_rt[0], self.temp_commit[self.config.sptag_len-1],
                 amount, clocked=True)

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
        with priority(PRI_RENAME):
            # augment the spec structure
            for rename_port_idx, (req_rename_sig, is_branch_sig, spectag_dyn, arch_idx_to_set, prf_idx_to_set) \
                in enumerate(self.rename_metas): \
                # augment the temp structure (the master will be updated)
                with zif(req_rename_sig):
                    write_entry(self.temp_commit[rename_port_idx], arch_idx_to_set,
                                self.isa_reg_file.amount,
                                renamed=1, prf_idx=prf_idx_to_set)
                # update the main structure
                with zif(req_rename_sig.land(is_branch_sig)):
                    if rename_port_idx == 0:
                        copy_row(self.spec_rt[OH(spectag_dyn)], self.temp_commit[0],
                                 self.isa_reg_file.amount, clocked=True)
                    copy_row(self.spec_rt[OH(spectag_dyn)], self.temp_dispatch[rename_port_idx-1],
                             self.isa_reg_file.amount, clocked=True)
