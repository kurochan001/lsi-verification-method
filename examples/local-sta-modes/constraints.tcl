# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# One file for both modes: `mode` selects the value of scan_enable and `period` the clock of that mode.
# `mutation` 0 gives the intended constraints; 1 and 2 change the period and the netlist, not this file.
create_clock -name core -period $period [get_ports clk]
create_clock -name aux -period 3.1 [get_ports aclk]
set_clock_transition 0.02 [all_clocks]
set_clock_uncertainty -setup 0.05 [all_clocks]
set_clock_uncertainty -hold 0.01 [all_clocks]
set_input_delay -clock core -max 0.6 [get_ports din]
set_input_delay -clock core -min 0.4 [get_ports din]
set_input_delay -clock core -max 0.4 [get_ports scan_in]
set_input_delay -clock core -min 0.3 [get_ports scan_in]
# scan_enable comes from the tester and settles late: it is a constant within a mode.
set_input_delay -clock core -max 1.9 [get_ports scan_enable]
set_input_delay -clock core -min 0.5 [get_ports scan_enable]
set_output_delay -clock core -max 0.5 [get_ports {dout scan_out}]
set_output_delay -clock core -min 0.1 [get_ports {dout scan_out}]
set_output_delay -clock aux -max 0.5 [get_ports aout]
set_output_delay -clock aux -min 0.1 [get_ports aout]
set_input_transition 0.02 [get_ports {din scan_in scan_enable}]
set_load 0.01 [all_outputs]

set scan_value [expr {$mode eq "scan"}]
if {$mutation == 4} {set scan_value [expr {!$scan_value}]}
if {$mutation != 3} {
    set_case_analysis $scan_value [get_ports scan_enable]
}

if {$mutation == 5} {
    set_false_path -from [get_clocks core] -to [get_clocks aux]
} elseif {$mutation != 6} {
    set_clock_groups -asynchronous -name core_aux -group core -group aux
}
