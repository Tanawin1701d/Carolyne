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

    def get_fix_tag(self, last_valid_spec_tag_dyn):
        """Get the column of the table: 00001 gets column 0 from all rows.

        - walked row by row: each row hands over its bit at the column the
          one-hot tag names (bit c of the tag muxes the row's bit c)
        - bit u of the mask comes from row u, so the bits assemble in row
          order into the selected column
        - the selected column is the kill mask, on its own named wire
        """
        sptag_len = self.config.sptag_len
        tag_ref   = to_ref(last_valid_spec_tag_dyn)
        fix_tag   = val(sptag_len, 0)
        for row_idx in range(sptag_len):
            row     = to_ref(self.storage[row_idx].fix_tag)
            row_bit = val(1, 0)
            for col_idx in range(sptag_len):
                row_bit = row_bit | mux(tag_ref[col_idx],
                                        row[col_idx],
                                        val(1, 0))
            fix_tag = fix_tag | (row_bit.extend(sptag_len) << row_idx)
        fix_wire  = wire(sptag_len, "mis_pred_fix_tag")
        fix_wire *= fix_tag
        return fix_wire

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
