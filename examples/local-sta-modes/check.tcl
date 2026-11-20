# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Prints what was measured. The verdict is derived by run.py, not here.
proc objects {name} {
    if {$name eq "-"} {return {}}
    if {[string first / $name] < 0} {set found [get_ports $name]} else {set found [get_pins $name]}
    if {[llength $found] != 1} {error "missing or ambiguous object $name"}
    return $found
}
if {[catch {
    read_liberty cells.lib
    read_verilog scan_core.v
    link_design scan_core
    source constraints.tcl
    source paths.tcl
    puts "AUDIT constraints [check_setup -verbose]"
    set records 0
    foreach {name from through to} $paths {
        set command [list find_timing_paths -from [objects $from] -to [objects $to] -group_path_count 1 -endpoint_path_count 1]
        if {$through ne "-"} {lappend command -through [objects $through]}
        foreach mode {max min} {
            set found [{*}$command -path_delay $mode]
            if {[llength $found] == 0} {
                puts "MISSING $name $mode"
            } elseif {[llength $found] != 1} {
                error "ambiguous timing path $name"
            } else {
                puts "MEASURE $name $mode [get_property [lindex $found 0] slack]"
            }
            incr records
        }
    }
    # Whether the crossing exists in the netlist under the constants of this mode, timed or not.
    foreach {name from to} $crossings {
        set starts [get_fanin -to [objects $to] -flat -startpoints_only]
        set names {}
        foreach pin $starts {lappend names [get_full_name $pin]}
        puts "CROSSING $name [expr {[lsearch -exact $names $from] >= 0}]"
    }
    report_checks -path_delay min_max -group_path_count 20 -digits 6
    puts "RESULT STA DONE records=$records"
} message]} {
    puts "TOOL_ERROR $message"
    exit 2
}
exit 0
