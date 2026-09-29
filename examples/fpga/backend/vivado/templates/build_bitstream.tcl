# build_bitstream.tcl — the whole Vivado flow for one emitted machine, static;
# its inputs come from build_params.tcl (filled per build):
#
#     vivado -mode batch -source build_bitstream.tcl -tclargs build_params.tcl
#
# The block design:
#
#     PS (M_AXI_HPM0_FPD) -> smartconnect -> axi_gpio  (bit 0 -> the machine's mrst)
#                                        -> axi_bram_ctrl -> BRAM_PORTA of the wrapper
#     pl_clk0 clocks everything; proc_sys_reset gives the AXI side its resetn
#
# What it leaves in $export_dir: $bit_name.bit and .hwh (same basename, PYNQ
# needs it), the reports, carolyne_bd.tcl, and build_summary.txt as `key value`
# lines the flow reads back. Any failure is a tcl error, so vivado exits non-zero.

if {$argc < 1} {
    error "usage: vivado -mode batch -source build_bitstream.tcl -tclargs build_params.tcl"
}
source [lindex $argv 0]

set bd_name   carolyne_bd
set core_cell carolyne_core
set t_start   [clock seconds]

# ---- helpers -------------------------------------------------------------------------

proc log2_exact {value} {
    set bits 0
    while {(1 << $bits) < $value} { incr bits }
    if {(1 << $bits) != $value} { error "not a power of two: $value" }
    return $bits
}

proc util_number {report pattern} {
    # the first number of the utilization table row whose name matches $pattern
    if {[regexp -line "\\|\\s*${pattern}\\s*\\|\\s*(\[0-9.\]+)" $report -> value]} { return $value }
    return 0
}

proc slack_of {kind} {
    # the worst slack of that check, or "" when nothing is timed
    set paths [get_timing_paths -max_paths 1 -nworst 1 {*}$kind]
    if {[llength $paths] == 0} { return "" }
    return [get_property SLACK [lindex $paths 0]]
}

proc write_summary {path stage synth_seconds impl_seconds} {
    set wns  [slack_of -setup]
    set whs  [slack_of -hold]
    set met  [expr {($wns eq "" || $wns >= 0) && ($whs eq "" || $whs >= 0)}]
    set util [report_utilization -return_string]
    set f    [open $path w]
    puts $f "stage $stage"
    puts $f "timing_met [expr {$met ? 1 : 0}]"
    if {$wns ne ""} { puts $f "wns_ns $wns" }
    if {$whs ne ""} { puts $f "whs_ns $whs" }
    puts $f "lut [util_number $util {CLB LUTs\*?}]"
    puts $f "lutram [util_number $util {LUT as Memory}]"
    puts $f "ff [util_number $util {Register as Flip Flop}]"
    puts $f "bram [util_number $util {Block RAM Tile}]"
    puts $f "dsp [util_number $util {DSPs}]"
    puts $f "synth_seconds $synth_seconds"
    puts $f "impl_seconds $impl_seconds"
    close $f
}

proc write_reports {export_dir prefix} {
    report_utilization    -file $export_dir/${prefix}_utilization.rpt
    report_timing_summary -file $export_dir/${prefix}_timing.rpt
    report_clock_networks -file $export_dir/${prefix}_clock_networks.rpt
}

# ---- project -------------------------------------------------------------------------

file mkdir $export_dir
create_project -force $project_name project -part $part
if {$board_part ne ""}        { set_property board_part $board_part [current_project] }
if {$board_connections ne ""} { set_property board_connections $board_connections [current_project] }
set_property target_language Verilog [current_project]

add_files -norecurse [glob $rtl_dir/*.v]
add_files -norecurse $wrapper_file
update_compile_order -fileset sources_1

# ---- block design --------------------------------------------------------------------

create_bd_design $bd_name

set ps [create_bd_cell -type ip -vlnv $ps_ip zynq_ps]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} $ps
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__MAXIGP0__DATA_WIDTH {32} \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $clock_mhz \
] $ps

set rst  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 ps_reset]
set smc  [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_fabric]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] $smc

set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 $reset_gpio_cell]
set_property -dict [list \
    CONFIG.C_ALL_OUTPUTS {1} \
    CONFIG.C_GPIO_WIDTH {1} \
    CONFIG.C_DOUT_DEFAULT {0x00000001} \
] $gpio

set bram [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl:4.1 $host_bram_cell]
set_property -dict [list \
    CONFIG.SINGLE_PORT_BRAM {1} \
    CONFIG.DATA_WIDTH {32} \
    CONFIG.READ_LATENCY {1} \
    CONFIG.ECC_TYPE {0} \
    CONFIG.PROTOCOL {AXI4} \
] $bram

set core [create_bd_cell -type module -reference $wrapper_module $core_cell]

# clocks and resets
set clk [get_bd_pins $ps/pl_clk0]
connect_bd_net $clk \
    [get_bd_pins $ps/maxihpm0_fpd_aclk] \
    [get_bd_pins $rst/slowest_sync_clk] \
    [get_bd_pins $smc/aclk] \
    [get_bd_pins $gpio/s_axi_aclk] \
    [get_bd_pins $bram/s_axi_aclk] \
    [get_bd_pins $core/clk]
connect_bd_net [get_bd_pins $ps/pl_resetn0] [get_bd_pins $rst/ext_reset_in]
connect_bd_net [get_bd_pins $rst/peripheral_aresetn] \
    [get_bd_pins $smc/aresetn] \
    [get_bd_pins $gpio/s_axi_aresetn] \
    [get_bd_pins $bram/s_axi_aresetn]

# the AXI fabric
connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_HPM0_FPD] [get_bd_intf_pins $smc/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $smc/M00_AXI]       [get_bd_intf_pins $gpio/S_AXI]
connect_bd_intf_net [get_bd_intf_pins $smc/M01_AXI]       [get_bd_intf_pins $bram/S_AXI]

# the window, and the reset line
connect_bd_intf_net [get_bd_intf_pins $bram/BRAM_PORTA] [get_bd_intf_pins $core/BRAM_PORTA]
connect_bd_net [get_bd_pins $gpio/gpio_io_o] [get_bd_pins $core/mrst]

# addresses: the window is exactly the bridge's, so the controller's memory
# depth (words) is the window's and its bram_addr is as wide as the wrapper's
assign_bd_address -offset $host_base_addr -range $window_bytes \
    -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $bram/S_AXI/Mem0] -force
assign_bd_address -offset $gpio_base_addr -range 4096 \
    -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $gpio/S_AXI/Reg] -force

validate_bd_design
set want_depth [expr {$window_bytes / 4}]
set got_depth  [get_property CONFIG.MEM_DEPTH [get_bd_cells $host_bram_cell]]
if {$got_depth eq "" || $got_depth != $want_depth} {
    error "the AXI BRAM controller holds '$got_depth' words, the bridge window needs $want_depth"
}
save_bd_design
write_bd_tcl -force $export_dir/${bd_name}.tcl

set wrapper [make_wrapper -files [get_files ${bd_name}.bd] -top]
add_files -norecurse $wrapper
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

# ---- synthesis -------------------------------------------------------------------------

set t_synth [clock seconds]
launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "synthesis did not finish: [get_property STATUS [get_runs synth_1]]"
}
set synth_seconds [expr {[clock seconds] - $t_synth}]

# the synthesis reports in BOTH modes: a failed implementation still leaves
# the utilization, the clock network and the post-synthesis timing to read
open_run synth_1
write_reports $export_dir synth
write_summary $export_dir/build_summary.txt synth $synth_seconds 0
puts "SYNTHESIS DONE in $synth_seconds s"
if {$synth_only} {
    puts "SYNTH-ONLY DONE"
    exit 0
}
close_design

# ---- implementation and the bitstream ---------------------------------------------------

set t_impl [clock seconds]
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "implementation did not finish: [get_property STATUS [get_runs impl_1]]"
}
set impl_seconds [expr {[clock seconds] - $t_impl}]

open_run impl_1
write_reports $export_dir impl
write_summary $export_dir/build_summary.txt impl $synth_seconds $impl_seconds

set bit [lindex [glob project/${project_name}.runs/impl_1/${bd_name}_wrapper.bit] 0]
set hwh [lindex [glob project/${project_name}.gen/sources_1/bd/${bd_name}/hw_handoff/${bd_name}.hwh] 0]
file copy -force $bit $export_dir/${bit_name}.bit
file copy -force $hwh $export_dir/${bit_name}.hwh
puts "BITSTREAM DONE in [expr {[clock seconds] - $t_start}] s: $export_dir/${bit_name}.bit"
exit 0
