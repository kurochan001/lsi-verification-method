# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Prints the annotation summary and the power of every instance. The verdict is derived by run.py.
if {[catch {
    read_liberty cells.lib
    read_verilog bank.v
    link_design $top
    create_clock -name clk -period 10 [get_ports clk]
    set_load 0.02 [get_ports q*]
    if {$use_vcd} {
        read_vcd -scope $scope wave.vcd
    }
    puts "BEGIN ANNOTATION"
    report_activity_annotation
    puts "END ANNOTATION"
    puts "BEGIN INSTANCES"
    report_power -instances [get_cells *] -digits 9
    puts "END INSTANCES"
    report_power -digits 9
    puts "RESULT POWER DONE"
} message]} {
    puts "TOOL_ERROR $message"
    exit 2
}
exit 0
