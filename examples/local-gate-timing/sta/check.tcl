# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Static timing of the netlist under constraints.tcl, then the SDF file for the simulation.
if {[catch {
    read_liberty cells.lib
    read_verilog netlist.v
    link_design mc_scale
    source constraints.tcl
    puts "AUDIT constraints [check_setup -verbose]"
    foreach mode {max min} {
        set paths [find_timing_paths -path_delay $mode -group_path_count 1]
        if {[llength $paths] != 1} {error "no worst $mode path"}
        puts "MEASURE $mode [get_property [lindex $paths 0] slack]"
    }
    report_checks -path_delay min_max -group_path_count 3 -digits 3
    if {$write_sdf} {write_sdf -divider / design.sdf}
    puts "RESULT STA"
} message]} {
    puts "TOOL_ERROR $message"
    exit 2
}
exit 0
