# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# The bench drives the inputs and samples the outputs at the falling edge, half a period after the
# rising edge. `corrected` chooses the constraints that describe the mutated design truthfully.
create_clock -name core -period $period [get_ports clk]
set half [expr {$period / 2.0}]
set_input_delay -clock core $half [get_ports {rst_n start a[*] b[*]}]
set_input_delay -clock core $cfg_delay [get_ports cfg]
set_output_delay -clock core $half [get_ports {busy done result[*]}]
set_input_transition 0.02 [all_inputs]
set_load 0.01 [all_outputs]
set launch [get_pins {a_q_*_reg/CLK b_q_*_reg/CLK cfg_q_reg/CLK}]
set capture [get_pins result_*_reg/D]
if {!($mutation == 1 && $corrected)} {
    # The result register loads two edges after the operands.
    set_multicycle_path 2 -setup -from $launch -to $capture
    set_multicycle_path 1 -hold -from $launch -to $capture
}
if {$mutation == 2 && !$corrected} {
    # "cfg is a static configuration input."
    set_false_path -from [get_ports cfg]
}
if {$mutation == 3 && $corrected} {
    set_propagated_clock [get_clocks core]
}
