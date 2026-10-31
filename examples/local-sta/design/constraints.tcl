# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
create_clock -name core -period $period [get_ports clk]
set_clock_transition 0.02 [get_clocks core]
set_clock_uncertainty -setup 0.05 [get_clocks core]
set_clock_uncertainty -hold 0.01 [get_clocks core]
if {$mutation != 3} {
    set_input_delay -clock core -max 0.6 [get_ports din]
    set_input_delay -clock core -min $input_min [get_ports din]
}
set_output_delay -clock core -max 0.5 [get_ports dout]
set_output_delay -clock core -min 0.1 [get_ports dout]
set_input_transition 0.02 [get_ports din]
set_load 0.01 [get_ports dout]
if {$mutation == 4} {
    set_false_path -from [get_pins u0/CLK] -to [get_pins u1/D]
}
