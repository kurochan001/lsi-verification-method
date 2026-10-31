# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
if {[catch {
    read_liberty cells.lib
    read_verilog pipeline.v
    link_design pipeline
    source constraints.tcl
    set clean [check_setup -verbose]
    puts "AUDIT constraints $clean"
    set missing 0
    set setup_bad 0
    set hold_bad 0
    foreach name {input internal output} from_type {ports pins pins} from {din u0/Q u1/Q} to_type {pins pins ports} to {u0/D u1/D dout} {
        set starts [get_$from_type $from]
        set ends [get_$to_type $to]
        if {[llength $starts]!=1 || [llength $ends]!=1} {error "path contract has missing/ambiguous objects"}
        foreach mode {max min} {
            set paths [find_timing_paths -from $starts -to $ends -path_delay $mode -group_path_count 1 -endpoint_path_count 1]
            if {[llength $paths]==0} {
                puts "MISSING $name $mode"
                set missing 1
            } elseif {[llength $paths]!=1} {
                error "ambiguous timing path"
            } else {
                set slack [get_property [lindex $paths 0] slack]
                puts "MEASURE $name $mode $slack"
                if {$slack<0} {
                    if {$mode eq "max"} {set setup_bad 1} else {set hold_bad 1}
                }
            }
        }
    }
    report_checks -path_delay min_max -group_path_count 10 -digits 6
    set label PASS
    if {!$clean} {set label STA_CONSTRAINT} elseif {$missing} {set label STA_PATH} elseif {$setup_bad} {set label STA_SETUP} elseif {$hold_bad} {set label STA_HOLD}
    puts "RESULT STA $label checks=6"
} message]} {
    puts "TOOL_ERROR $message"
    exit 2
}
if {$label ne "PASS"} {exit 1}
exit 0
