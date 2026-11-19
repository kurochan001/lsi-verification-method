# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Measure what each group of paths needs, before a period is chosen: delay plus the setup time.
proc need {name paths} {
    if {[llength $paths] != 1} {error "no single worst path for $name"}
    puts "NEED $name [expr {100.0 - [get_property [lindex $paths 0] slack]}]"
}
if {[catch {
    read_liberty cells.lib
    read_verilog netlist.v
    link_design mc_scale
    create_clock -name core -period 100 [get_ports clk]
    set_input_delay -clock core 0 [get_ports {rst_n start cfg a[*] b[*]}]
    set_output_delay -clock core 0 [get_ports {busy done result[*]}]
    set_input_transition 0.02 [all_inputs]
    set_load 0.01 [all_outputs]
    set launch [get_pins {a_q_*_reg/CLK b_q_*_reg/CLK cfg_q_reg/CLK}]
    set capture [get_pins result_*_reg/D]
    if {[llength $launch] != 13 || [llength $capture] != 13} {error "operand or result registers missing"}
    need multicycle [find_timing_paths -from $launch -to $capture -path_delay max -group_path_count 1]
    need cfg [find_timing_paths -from [get_ports cfg] -to [get_pins cfg_q_reg/D] -path_delay max -group_path_count 1]
    need input [find_timing_paths -from [get_ports {rst_n start cfg a[*] b[*]}] -path_delay max -group_path_count 1]
    set_false_path -from $launch -to $capture
    need single [find_timing_paths -from [all_registers -clock_pins] -path_delay max -group_path_count 1]
    puts "RESULT PROBE"
} message]} {
    puts "TOOL_ERROR $message"
    exit 2
}
exit 0
