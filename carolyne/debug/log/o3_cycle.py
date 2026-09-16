# ONE CYCLE OF THE O3 CORE AS ONE ROW of the slot table.
#
# Two halves, and the split is the point:
#   O3SimHandles   every probe and signal the log reads, NAMED ONE BY ONE and
#                  resolved once — no reflection, no path strings
#   O3CycleLogger  reads them GATE FIRST and formats through o3_cell
#
# GATE FIRST is what keeps a cycle cheap: a lane's `valid`, a station row's
# `valid`, a commit lane's `commit_ok` and the store port's `enable` are read
# before anything they guard, so an idle cycle costs a few dozen handle reads
# where a full read would cost about eighteen hundred.
#
# The field NAMES come from the machine's own vocabulary (common_field,
# operand_field), so a record that grows a field does not need a change here.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from carolyne.debug.log import o3_cell        as CELL
from carolyne.debug.log import o3_cell_fields as FIELDS
from carolyne.debug.log.events import COMMIT, MEM_WRITE, MMIO, REDIRECT, CycleEvent
from carolyne.debug.log.slot_writer import Column, Row, SlotTable
from carolyne.debug.sim import KarraySimProbe, read_value
from carolyne.uarch.o3 import common_field as CF
from carolyne.uarch.o3.operand_field import ACTIVE, AR_IDX, PR_IDX, VALID, field_name

# ---- the columns ------------------------------------------------------------------
CYCLE_COL, REG_COL, PRF_COL      = "CYCLE/MPFT", "RT/ARF", "PRF"
FETCH_COL, DECODE_COL, DISP_COL  = "FETCH", "DECODE", "DISPATCH"
RSV_COL, ISSUE_COL, EXEC_COL     = "RSV", "ISSUE", "EXEC"
ROB_COL, STBUF_COL, MEM_COL      = "ROB/COMMIT", "STBUF", "MEM"

O3_COLUMNS = (Column(CYCLE_COL,  20), Column(REG_COL,    40), Column(PRF_COL,   25),
              Column(FETCH_COL,  25), Column(DECODE_COL, 30), Column(DISP_COL,  30),
              Column(RSV_COL,    35), Column(ISSUE_COL,  25), Column(EXEC_COL,  35),
              Column(ROB_COL,    25), Column(STBUF_COL,  25), Column(MEM_COL,   25))


# ---- the handles ---------------------------------------------------------------------

def convert_list(probes: Sequence[Any], holder: Any, name: str) -> List[Any]:
    """Each model probe of a list, converted against its own manifest node.

    - an EMPTY list reaches no manifest node at all (the writer drops a
      container with nothing in it), so it answers [] without asking
    """
    if not probes:
        return []
    return [probe.convert(node) for probe, node in zip(probes, getattr(holder, name))]


class ExecHandles:
    """One execution complex: its stage arbiters and the records between them."""

    def __init__(self, label: str, exu: Any, k_exu: Any) -> None:
        self.label       = label
        self.stage_metas = convert_list(exu.dbg_stage_metas, k_exu, "dbg_stage_metas")
        self.stage_srcs  = convert_list(exu.dbg_stage_srcs,  k_exu, "dbg_stage_srcs")
        self.resolve     = exu.dbg_resolve.convert(k_exu.dbg_resolve)


class StationHandles:
    """One reservation station: its table, its issue paths and their complexes."""

    def __init__(self, label: str, rsv: Any, k_rsv: Any, execs: Sequence[ExecHandles]) -> None:
        self.label        = label
        self.table        = rsv.dbg_table.convert(k_rsv.dbg_table)
        self.issue_metas  = convert_list(rsv.dbg_issue_metas, k_rsv, "dbg_issue_metas")
        self.exec_src     = convert_list(rsv.dbg_exec_src,    k_rsv, "dbg_exec_src")
        self.issue_ready  = list(k_rsv.issue_ready)
        self.execs        = tuple(execs)
        self.src_slots    = tuple(rsv.has_src_arch_operands)
        self.has_pc       = CF.PC in self.table.fields()


class RegClassHandles:
    """One architectural register class: its committed file, its physical file,
    and the rename table's master plane."""

    def __init__(self, name: str, blocks: Any, k_blocks: Any) -> None:
        self.name       = name
        self.arf        = blocks.arf.dbg_storage.convert(k_blocks.arf.dbg_storage)
        self.prf        = None
        self.rt         = None
        self.free_entry = None
        self.next_index = None
        if hasattr(blocks, "prf"):
            self.prf        = blocks.prf.dbg_storage.convert(k_blocks.prf.dbg_storage)
            self.rt         = blocks.rt.dbg_master_rt.convert(k_blocks.rt.dbg_master_rt).plane(0)
            self.free_entry = k_blocks.prf.free_entry
            self.next_index = k_blocks.prf.next_index


class O3SimHandles:
    """Every probe and signal the log reads, resolved once against one KSim."""

    def __init__(self, model: Any, k: Any) -> None:
        core, k_core = model.core, k.core

        # front end
        self.fetch_meta     = core.fetch   .dbg_fetch_meta   .convert(k_core.fetch   .dbg_fetch_meta)
        self.fetch_table    = core.fetch   .dbg_fetch        .convert(k_core.fetch   .dbg_fetch)
        self.fetch_pc       = k_core.fetch.pc
        self.decode_meta    = core.decode  .dbg_decode_meta  .convert(k_core.decode  .dbg_decode_meta)
        self.decode_table   = core.decode  .dbg_decode       .convert(k_core.decode  .dbg_decode)
        self.dispatch_meta  = core.dispatch.dbg_dispatch_meta.convert(k_core.dispatch.dbg_dispatch_meta)
        self.dispatch_bus   = core.dispatch.dbg_dispatch_bus .convert(k_core.dispatch.dbg_dispatch_bus)
        self.dispatch_ready = k_core.dispatch.ready_to_go

        # the reorder buffer and commit
        self.commit_meta    = core.rob.dbg_commit_meta.convert(k_core.rob.dbg_commit_meta)
        self.rob_table      = core.rob.dbg_table      .convert(k_core.rob.dbg_table)
        self.rob_com_row    = core.rob.dbg_com_row    .convert(k_core.rob.dbg_com_row)
        self.rob_commit_ok  = list(k_core.rob.commit_ok)
        self.rob_alloc_ptr  = k_core.rob.alloc_ptr
        self.rob_com_ptr    = k_core.rob.com_ptr
        self.rob_used       = k_core.rob.used_entry_cnt
        # what MOVED the count this cycle, and whether the group fit: a count
        # that disagrees with its pointers is read here
        self.rob_alloc_cnt  = k_core.rob.alloc_cnt
        self.rob_commit_cnt = k_core.rob.commit_cnt
        self.rob_fits       = k_core.rob.dispatch_fits

        # the store buffer
        self.retire_meta  = core.store_buf.dbg_retire_meta.convert(k_core.store_buf.dbg_retire_meta)
        self.st_buf_table = core.store_buf.dbg_table      .convert(k_core.store_buf.dbg_table)
        self.st_buf_alloc = k_core.store_buf.alloc_ptr
        self.st_buf_com   = k_core.store_buf.com_ptr
        self.st_buf_ret   = k_core.store_buf.ret_ptr

        # one entry per station, each with its own complexes
        self.stations : List[StationHandles] = []
        for lane_idx, lane in enumerate(core.issue_lanes):
            k_lane = k_core.issue_lanes[lane_idx]
            execs  = [ExecHandles(exu.label, exu, k_lane[1][unit_idx])
                      for unit_idx, exu in enumerate(lane.execs)]
            self.stations.append(StationHandles(lane.rsv.label, lane.rsv, k_lane[0], execs))

        # rename bookkeeping and the register files
        self.mpft        = core.mpft.dbg_storage.convert(k_core.mpft.dbg_storage)
        self.free_tag    = k_core.tag_gen.free_tag
        self.next_tag    = k_core.tag_gen.next_tag
        self.reg_classes = [RegClassHandles(name, blocks, k_core.dbg_reg_arch[name])
                            for name, blocks in core.dbg_reg_arch.items()]

        # the memories: what each port addressed, and the one store path
        self.imem_reads = convert_list(model.instr_mem.dbg_read_wires, k.instr_mem, "dbg_read_wires")
        self.dmem_load  = model.data_mem.dbg_read_wires[0] .convert(k.data_mem.dbg_read_wires[0])
        self.dmem_store = model.data_mem.dbg_write_wires[0].convert(k.data_mem.dbg_write_wires[0])


# ---- what changed since last cycle -----------------------------------------------------

class RegChangeTracker:
    """Remembers one table's rendered rows, and answers what changed."""

    def __init__(self) -> None:
        self.last : Dict[int, str] = {}

    def diff(self, texts: Sequence[str]) -> List[Tuple[int, str]]:
        changed = [(idx, text) for idx, text in enumerate(texts)
                   if self.last.get(idx) != text]
        self.last = dict(enumerate(texts))
        return changed


# ---- the logger ----------------------------------------------------------------------

class O3CycleLogger:
    """Reads one cycle off the handles and formats it as one slot-table row."""

    def __init__(self, handles: O3SimHandles, config: Any, rob_rows: int = 4) -> None:
        self.handles   = handles
        self.config    = config
        self.rob_rows  = rob_rows
        self.table     = SlotTable(O3_COLUMNS)
        self.col       = {column.name: idx for idx, column in enumerate(O3_COLUMNS)}
        self.tag_bits  = config.sptag_len
        self.uop_names = {uop.uop_idx: uop.name for uop in config.isa.uops}
        self.build_field_names()
        self.arf_change = {cls.name: RegChangeTracker() for cls in handles.reg_classes}
        self.rt_change  = {cls.name: RegChangeTracker() for cls in handles.reg_classes}
        self.prf_change = {cls.name: RegChangeTracker() for cls in handles.reg_classes}
        self.pc_was     : Optional[int] = None

    # --- the names every cell reads -----------------------------------------------
    def build_field_names(self) -> None:
        """Every field name, derived once from the ISA's own operands."""
        isa   = self.config.isa
        dests = [opr for opr in isa.used_atomic_operands() if opr.is_dest and opr.has_arch]

        self.dest_slots      = [FIELDS.SlotFields(label  = opr.name,
                                                  active = field_name(ACTIVE, opr),
                                                  pr_idx = field_name(PR_IDX, opr),
                                                  ar_idx = field_name(AR_IDX, opr))
                                for opr in dests]
        self.fetch_fields    = FIELDS.FetchFields(valid = CF.VALID,
                                                  instr = CF.INSTR,
                                                  pc    = CF.PC)
        self.decode_fields   = FIELDS.DecodeFields(valid     = CF.VALID,
                                                   uop_idx   = CF.UOP_IDX,
                                                   pc        = CF.PC,
                                                   rsv_id    = CF.RSV_ID,
                                                   is_branch = CF.IS_BRANCH,
                                                   is_store  = CF.IS_STORE)
        self.dispatch_fields = FIELDS.DispatchFields(valid       = CF.VALID,
                                                     uop_idx     = CF.UOP_IDX,
                                                     rob_des_idx = CF.ROB_DES_IDX,
                                                     is_spec     = CF.IS_SPEC,
                                                     spec_tag    = CF.SPEC_TAG,
                                                     dest_pr_idx = self.dest_slots)
        self.rob_fields      = FIELDS.RobFields(wb_fin    = CF.WB_FIN,
                                                pc        = CF.PC,
                                                is_branch = CF.IS_BRANCH,
                                                is_store  = CF.IS_STORE,
                                                dests     = self.dest_slots)
        self.st_buf_fields   = FIELDS.StBufFields(busy     = CF.BUSY,
                                                  complete = CF.COMPLETE,
                                                  is_spec  = CF.IS_SPEC,
                                                  spec_tag = CF.SPEC_TAG,
                                                  mem_addr = CF.MEM_ADDR,
                                                  data     = CF.DATA)
        self.rsv_fields      = [self.station_fields(station) for station in self.handles.stations]

    def station_fields(self, station: StationHandles) -> FIELDS.RsvFields:
        slots = [FIELDS.SlotFields(label  = opr.name,
                                   active = field_name(ACTIVE, opr),
                                   valid  = field_name(VALID,  opr))
                 for opr in station.src_slots]
        return FIELDS.RsvFields(valid       = CF.VALID,
                                uop_idx     = CF.UOP_IDX,
                                rob_des_idx = CF.ROB_DES_IDX,
                                is_spec     = CF.IS_SPEC,
                                spec_tag    = CF.SPEC_TAG,
                                src_slots   = slots,
                                uop_names   = self.uop_names,
                                pc          = CF.PC if station.has_pc else None)

    # --- one cycle -------------------------------------------------------------------
    def record(self, cycle: int, events: Sequence[CycleEvent]) -> Row:
        """One row: every column, each read gate first."""
        row = self.table.new_row()
        self.put_cycle   (row, cycle)
        self.put_registers(row, events)
        self.put_front_end(row)
        self.put_stations (row)
        self.put_back_end (row, events)
        self.put_memory   (row, events)
        return row

    def add(self, row: Row, column: str, lines: Sequence[str]) -> None:
        row.add_all(self.col[column], lines)

    def put_cycle(self, row: Row, cycle: int) -> None:
        lines = [str(cycle), f"tag f:{CELL.cvt_val_to_dec(read_value(self.handles.free_tag))}"
                             f" n:{CELL.cvt_val_to_bin(read_value(self.handles.next_tag), self.tag_bits)}"]
        lines += CELL.mpft_lines(self.handles.mpft.rows(), CF.FIX_TAG, self.tag_bits)
        self.add(row, CYCLE_COL, lines)

    def put_registers(self, row: Row, events: Sequence[CycleEvent]) -> None:
        """Architectural and rename state, as CHANGE lines only."""
        banner = ["CHANGE FROM REDIRECT"] if any(e.kind == REDIRECT for e in events) else []
        reg_lines, prf_lines = list(banner), []
        for cls in self.handles.reg_classes:
            arf     = [CELL.cvt_val_to_hex(value.get(CF.DATA)) for value in cls.arf.rows()]
            changed = self.arf_change[cls.name].diff(arf)
            if changed:
                reg_lines.append(f"{cls.name} arf")
                reg_lines += CELL.reg_change_lines(changed, per_line=3)
            if cls.rt is not None:
                names   = [CELL.rename_text(r, CF.RENAMED, CF.PRF_IDX) for r in cls.rt.rows()]
                changed = self.rt_change[cls.name].diff(names)
                if changed:
                    reg_lines.append(f"{cls.name} rt")
                    reg_lines += CELL.reg_change_lines(changed, per_line=6)
            if cls.prf is not None:
                prf_lines.append(f"{cls.name} f:{CELL.cvt_val_to_dec(read_value(cls.free_entry))}"
                                 f" n:{CELL.cvt_val_to_dec(read_value(cls.next_index))}")
                phys = [f"{CELL.cvt_val_to_dec(r.get(CF.FIN))}/{CELL.cvt_val_to_hex(r.get(CF.DATA))}"
                        for r in cls.prf.rows()]
                prf_lines += CELL.reg_change_lines(self.prf_change[cls.name].diff(phys), per_line=2)
        self.add(row, REG_COL, reg_lines)
        self.add(row, PRF_COL, prf_lines)

    def put_front_end(self, row: Row) -> None:
        pc = read_value(self.handles.fetch_pc)
        self.add(row, FETCH_COL, CELL.fetch_lines(
            self.handles.fetch_meta.pip_status(), pc,
            self.read_lane_rows(self.handles.fetch_table, CF.VALID), self.fetch_fields))
        self.add(row, DECODE_COL, CELL.decode_lines(
            self.handles.decode_meta.pip_status(),
            self.read_lane_rows(self.handles.decode_table, CF.VALID),
            self.uop_names, self.decode_fields))
        self.add(row, DISP_COL, CELL.dispatch_lines(
            self.handles.dispatch_meta.pip_status(), read_value(self.handles.dispatch_ready),
            self.read_lane_rows(self.handles.dispatch_bus, CF.VALID),
            self.uop_names, self.dispatch_fields, self.tag_bits))

    def put_stations(self, row: Row) -> None:
        """Every live entry, every issue path, every busy execution stage."""
        rsv_lines, issue_lines, exec_lines = [], [], []
        for station, fields in zip(self.handles.stations, self.rsv_fields):
            live = station.table.live_rows(valid=CF.VALID)
            if live:
                rsv_lines.append(f"--- {station.label} ---")
            for idx in live:
                rsv_lines += CELL.rsv_entry_lines(idx, station.table.row(idx), True,
                                                  fields, self.tag_bits)
            for unit_idx, meta in enumerate(station.issue_metas):
                status = meta.pip_status()
                ready  = read_value(station.issue_ready[unit_idx])
                if ready != 1 and status != "RUNNING":
                    continue
                issue_lines.append(f"{station.label}.i{unit_idx} {status}")
                slot = station.exec_src[unit_idx].row(0)
                if slot.get(CF.VALID) == 1:
                    issue_lines.append(f"  {CELL.cvt_uop_idx_to_name(self.uop_names, slot.get(CF.UOP_IDX))}"
                                       f" rob:{CELL.cvt_val_to_dec(slot.get(CF.ROB_DES_IDX))}")
            for exu in station.execs:
                exec_lines += self.exec_stage_lines(exu, station)
        self.add(row, RSV_COL,   rsv_lines)
        self.add(row, ISSUE_COL, issue_lines)
        self.add(row, EXEC_COL,  exec_lines)

    def exec_stage_lines(self, exu: ExecHandles, station: StationHandles) -> List[str]:
        """One line per stage that is doing something, and what it holds."""
        lines = []
        if exu.resolve.declares:
            if exu.resolve.read_mis_pred() == 1:
                lines.append(f"{exu.label} MISPRED")
                lines.append(f"  -> {CELL.cvt_val_to_hex(exu.resolve.read_redirect_pc())}")
            elif exu.resolve.read_suc_pred() == 1:
                lines.append(f"{exu.label} SUCPRED")
        for stage_idx, meta in enumerate(exu.stage_metas):
            status = meta.pip_status()
            if status in ("IDLE", "BUSY"):
                continue
            lines.append(f"{exu.label} s{stage_idx} {status}")
            src = (station.exec_src[0].row(0) if stage_idx == 0
                   else exu.stage_srcs[stage_idx - 1].row(0))
            lines.append(f"  {CELL.cvt_uop_idx_to_name(self.uop_names, src.get(CF.UOP_IDX))}"
                         f" rob:{CELL.cvt_val_to_dec(src.get(CF.ROB_DES_IDX))}")
        return lines

    def put_back_end(self, row: Row, events: Sequence[CycleEvent]) -> None:
        committed = [event.facts for event in events if event.kind == COMMIT]
        live      = self.handles.rob_table.live_rows()[:self.rob_rows]
        rob_lines = CELL.rob_lines(
            read_value(self.handles.rob_alloc_ptr), read_value(self.handles.rob_com_ptr),
            read_value(self.handles.rob_used), committed,
            [(idx, self.handles.rob_table.row(idx)) for idx in live], self.rob_fields)
        # what moved the count this cycle: a count that disagrees with its
        # pointers is only readable with both terms beside it
        rob_lines.insert(1, f"+{CELL.cvt_val_to_dec(read_value(self.handles.rob_alloc_cnt))}"
                            f" -{CELL.cvt_val_to_dec(read_value(self.handles.rob_commit_cnt))}"
                            f" fit:{CELL.cvt_val_to_dec(read_value(self.handles.rob_fits))}")
        self.add(row, ROB_COL, rob_lines)

        st_lines = [f"a:{CELL.cvt_val_to_dec(read_value(self.handles.st_buf_alloc))}"
                    f" c:{CELL.cvt_val_to_dec(read_value(self.handles.st_buf_com))}"
                    f" r:{CELL.cvt_val_to_dec(read_value(self.handles.st_buf_ret))}"]
        for idx in self.handles.st_buf_table.live_rows(valid=CF.BUSY):
            st_lines += CELL.st_buf_entry_lines(idx, self.handles.st_buf_table.row(idx),
                                                self.st_buf_fields, self.tag_bits)
        self.add(row, STBUF_COL, st_lines)

    def put_memory(self, row: Row, events: Sequence[CycleEvent]) -> None:
        """What each instruction port addressed, and the store this cycle."""
        lines = []
        for lane, port in enumerate(self.handles.imem_reads):
            if read_value(port.valid) != 1:
                continue
            lines.append(f"i{lane} @{CELL.cvt_val_to_dec(port.read_index())}"
                         f".b{CELL.cvt_val_to_dec(port.read_bank())}")
        for event in events:
            if event.kind in (MMIO, MEM_WRITE):
                door = event.facts.get("door", "")
                lines.append(f"ST {door or '@' + CELL.cvt_val_to_dec(event.facts['index'])}"
                             f" = {CELL.cvt_val_to_hex(event.facts['data'])}")
            elif event.kind == REDIRECT:
                lines.append(f"REDIR {CELL.cvt_val_to_hex(event.facts['to'])}")
        self.add(row, MEM_COL, lines)

    @staticmethod
    def read_lane_rows(probe: KarraySimProbe, valid_field: str) -> CELL.LaneRows:
        """One entry per lane, read only where its `valid` is set.

        - a lane that was not read carries that one field and nothing else, so a
          cell still finds a row at the lane's own position
        """
        lane_rows = []
        for idx in range(len(probe)):
            if read_value(getattr(probe.table[idx], valid_field)) == 1:
                lane_rows.append(probe.row(idx))
            else:
                lane_rows.append({valid_field: 0})
        return lane_rows
