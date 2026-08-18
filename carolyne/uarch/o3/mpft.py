from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.common.karray_util import OH
from carolyne.uarch.o3.config import CPUO3_Config


class MpftEntry(Karray):
    fix_tag = kaf()


class Mpft(Module):

    # mispredict | rename | sucpredict

    def __init__(self,
                 config: CPUO3_Config,
                 rename_ports: int):

        self.config = config
        self.rename_ports = rename_ports

        super().__init__()


    @init
    def com_declare(self):

        self.storage = MpftEntry(
            HwComponentType.REG,
            (self.config.sptag_len,),
            "mpft",
            fix_tag = self.config.sptag_len
        )

        #it should be list of (is_branch, tag_assign)
        self.rename_sigs = [None for _ in range(self.rename_ports)]

    def on_mis_pred(self, last_valid_spec_tag_dyn):
        sp_tag_len = self.config.sptag_len
        for row_idx in range(sp_tag_len):
            self.storage[row_idx] |= mux(last_valid_spec_tag_dyn[row_idx], last_valid_spec_tag_dyn, 0)

    def on_book_rename(self, port_idx, is_branch_sig, tag_sig):
        self.rename_sigs[port_idx] = (is_branch_sig, tag_sig)

    def on_rename(self, cur_sp_tag_dyn):
        temp_next_sp_tag_dyn = cur_sp_tag_dyn
        for port_idx in range(self.rename_ports):

            valid, tag_idx = self.rename_sigs[port_idx]
            temp_next_sp_tag_dyn = mux(valid,
                                       temp_next_sp_tag_dyn | tag_idx,
                                       temp_next_sp_tag_dyn)
            with zif(valid):
                self.storage[OH(tag_idx)] |= temp_next_sp_tag_dyn


    def on_suc_pred(self, last_valid_spec_tag_dyn):
        sp_tag_len = self.config.sptag_len
        for row_idx in range(sp_tag_len):
            self.storage[row_idx] |= to_ref(self.storage[row_idx].fix_tag) & ~last_valid_spec_tag_dyn
