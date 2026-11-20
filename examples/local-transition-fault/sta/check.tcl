# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Static timing of the scan netlist in functional mode with an ideal clock, then the SDF file.
# With period 100 the run only measures: NEED is the longest flop-to-flop delay plus the setup time.
if {[catch {
    read_liberty cells.lib
    read_verilog netlist.v
    link_design tf_core
    create_clock -name core -period $period [get_ports clk]
    # The bench moves the inputs and reads scan_out between the pulses, far from every edge.
    set_input_delay -clock core 0 [get_ports {scan_enable scan_in x}]
    set_output_delay -clock core 0 [get_ports scan_out]
    set_input_transition 0.02 [all_inputs]
    set_load 0.01 [all_outputs]
    puts "AUDIT constraints [check_setup -verbose]"
    set flops [all_registers -clock_pins]
    if {[llength $flops] != 4} {error "four scan flops expected"}
    set paths [find_timing_paths -from $flops -to [all_registers -data_pins] -path_delay max -group_path_count 1]
    if {[llength $paths] != 1} {error "no flop-to-flop path"}
    puts "NEED [expr {$period - [get_property [lindex $paths 0] slack]}]"
    foreach mode {max min} {
        set paths [find_timing_paths -path_delay $mode -group_path_count 1]
        if {[llength $paths] != 1} {error "no worst $mode path"}
        puts "MEASURE $mode [get_property [lindex $paths 0] slack]"
    }
    report_checks -path_delay min_max -group_path_count 2 -digits 3
    if {$write_sdf} {write_sdf -divider / design.sdf}
    puts "RESULT STA"
} message]} {
    puts "TOOL_ERROR $message"
    exit 2
}
exit 0
