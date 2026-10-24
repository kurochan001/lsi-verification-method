# Where Icarus Verilog 13.0 and Verilator 5.052 differ from the standard

The expected outputs of the suite follow IEEE 1800-2023 and are checked with
Icarus Verilog 13.0 and Verilator 5.052 (see "Where the expected outputs come
from" in the README). This file lists the places found so far where one of
these releases gives another result than the cited clauses require, or
accepts a design that the standard makes illegal, with the tests that show
it.

Constructs that a release does not support at all, where it stops with an
error, a "sorry" or "unsupported" message, are not listed: they show as known
differences that do not compile. Verilator's lack of x, z and strengths, as a
two-state simulator, is not listed either. Nor is an illegal design that a
release rejects only because it does not support a construct in it: when that
error falls on the line the test names, the runner counts it, and the comment
of the test says why `:oracle:` does not list the release.

None of these has been reported to the projects. Before reporting one, check
it with the current development version: the [nightly
report](https://github.com/kurochan001/kirimasim-tests/tree/results#readme)
runs the latest `master` of both, and a known difference that a development
version now matches shows there as `NOW MATCHES` for Icarus Verilog or as a
new match.

When a new test finds such a place, add it here, and say it in the comment
of the test as well.

## Icarus Verilog 13.0

### Results

| Clause | What Icarus Verilog 13.0 does | Tests |
| --- | --- | --- |
| 11.4.11 | With an x or z condition, `?:` gives z where both operands have z in the same bit; Table 11-20 gives x. | `gen/ch11/test_gen_xz_cond_07`, `_08` |
| 28.12.1, 28.12.4 | On wand, wor, triand and trior nets it ignores the strengths of the drivers: it combines their values with the logic function and gives the result strong strength. The stronger driver has to win, and only drivers of equal strength are combined, at that strength. | the 29 `gen/ch28/test_gen_strength_{wand,wor,triand,trior}_*` tests with `:oracle: spec` |
| 30.4.4.1, 32.4.1 | It treats the condition of a state-dependent path as false when it is x or z; it has to be treated as true, also for the COND entry of an SDF file. | `ch30/test_specify_condition_unknown_true`, `ch32/test_sdf_cond_unknown_true` |
| 28.14 | rcmos passes a strong drive as strong; it has to reduce it to pull, as rtran and rtranif do. | `ch28/test_rcmos_reduction` |
| 29.7 | The delay of a sequential UDP instance also delays its initial value, which shows x until then. | `ch29/test_udp_initial_value_not_delayed` |
| 24.3 | When a program's initial procedures end, the threads they forked go on running; they have to end with the program. | `ch24/test_program_end_kills_descendants` |
| 24.5, 24.3.1 | A program's thread, and a module task it calls, run in the Active region with the module's processes instead of in the Reactive region: the call sees a variable before the nonblocking update of its time step, and runs before the module's own processes of the time step it resumes in. | `ch24/test_program_calls_module_task` |
| 24.3.1 | A program's process sees the values from before the nonblocking updates of its time step (Verilator 5.052 too). | `ch24/test_program_reactive_sees_nba`, `ch24/test_program_stimulus_after_clock_edge` |
| 10.6.1, 4.9.2 | `assign` (procedural continuous) evaluates its right-hand side once, so the variable does not follow later changes (it warns about this; Verilator 5.052 does the same). | `ch4/test_sched_procedural_assign_deassign` |
| 11.5.2, 7.4.5 | Reading a 2-state memory at an invalid address gives x instead of the default value 0. | `ch11/test_memory_invalid_address_2state` |
| 22.5.3 | It does not know `` `undefineall `` and treats it as an empty macro, so the macros stay defined. | `ch22/test_undefineall` |
| 32.5 | It applies INCREMENT delays of an SDF file as absolute ones. | `ch32/test_sdf_increment_absolute` |
| 32.3 | It ignores the TIMESCALE of the DELAYFILE and reads delay values in the time unit of the design. | `ch32/test_sdf_timescale` |
| 32.4.1 | It leaves module paths with COND entries at their specify delays. | `ch32/test_sdf_cond_iopath` |
| 32.4.3 | It does not read the LABEL section of an SDF file. | `ch32/test_sdf_label_specparam` |
| 32.9 | It uses only the first two arguments of `$sdf_annotate`, and rejects an empty module instance argument. | `ch32/test_sdf_mtm_spec`, `ch32/test_sdf_scale_factors` |
| 33 | It skips config declarations without an error, so the design is not configured. | `ch33/test_config_cell_use`, `ch33/test_config_cell_with_library`, `ch33/test_config_binding_nested`, `ch33/test_config_defparam_precedence`, `ch33/test_config_design_top`, `ch33/test_config_design_two_tops`, `ch33/test_config_instance_deep_path`, `ch33/test_config_instance_over_cell`, `ch33/test_config_instance_use`, `ch33/test_config_library_binding_format` |
| 31 | It skips timing checks such as `$setup`, `$timeskew` and `$fullskew` without an error, so their notifiers never change. | `ch31/test_timing_timeskew_flags`, `ch31/test_timing_timeskew_remain_active`, `ch31/test_timing_fullskew_event_based`, `ch31/test_timing_notifier_x_and_z` and the other tests of chapter 31 with `:oracle: spec`, `ch32/test_sdf_recrem_limits`, `ch32/test_sdf_timing_check_limits`, `ch32/test_sdf_separate_setup_hold`, `ch32/test_sdf_width_period_limits` |
| 36.10.1, 38.36.2 | `vpi_chk_error` reports no error after `vpi_register_cb` refuses a callback that the standard makes an error, and a cbAtStartOfSimTime with delay 0 makes it stop on an internal assertion. | `ch36/test_vpi_chk_error_callbacks`, `ch36/test_vpi_chk_error_status` |
| 37.42 | It evaluates an argument of a user-defined system task that the application never reads; such an argument must not be evaluated. | `ch36/test_vpi_systf_argument_on_demand` |
| 38.34 | `vpi_put_value` keeps every scheduled event in all three delay modes; inertial delay has to cancel the pending ones. | `ch38/test_vpi_put_value_delay_modes` |
| 38.36.1 | A value change callback on a named event gets a value structure. | `ch38/test_vpi_value_change_event` |
| 36.8.1 | User-defined system functions need their return types at compile time (in a `.sft` file): without one, it takes a call in procedural code as a 32-bit result, does not compile a call in a continuous assignment, and stops at the first real result. | `ch36/test_vpi_systf_function_types`, `ch36/test_vpi_systf_function_in_continuous_assign` |
| 9.6.1, 9.6.3 | It stops with an internal assertion. | `ch9/test_wait_fork_disable_fork` |
| 7.10.2.4, 7.10.2.5, 7.4.5 | `pop_front()` and `pop_back()` on an empty queue of int give x, and an int variable then holds x; Table 7-1 gives 0. | `ch7/test_queue_method_edges` |
| 20.17.2 | `$stacktrace` called as a function makes the compiler stop on an internal assertion. | `ch20/test_stacktrace_function` |
| 37.3.5 | `vpi_put_value` on a system task argument whose index has a side effect stops on an internal assertion instead of reporting an error. | `ch37/test_vpi_put_value_side_effect` |
| 30.7.4.2 | A showcancelled declaration has no effect: a negative pulse leaves the output unchanged instead of showing x. | `ch30/test_negative_pulse_cancelled` |
| 29.3.2 | A combinational UDP that declares its output reg makes it stop on an internal assertion instead of reporting the error. | `ch29/test_illegal_udp_combinational_reg` |
| 6.21, 7.5 | A continuous assignment to an element of a dynamic array makes it stop on an internal assertion instead of reporting the error. | `ch6/test_illegal_dynamic_array_element_continuous` |
| 13.4.4 | It rejects a function whose fork-join_none spawns a process with a delay, as if the function had the delay; the spawned process may hold any statement of a task. | `ch4/test_sched_fork_join_none_in_function` |
| 9.6.3 | disable fork in a task does not end the processes that the calling process spawned before the call. | `ch4/test_sched_disable_fork_in_called_task` |
| 21.2.1.3 | `%h` of an expression, such as a function call, whose top digit has fewer than four bits, all x, prints X instead of x; a variable with the same value prints x. | `gen/ch13/test_gen_wide_subroutine_w65_4state` |
| 7.4.5, 11.5.1 | A write to a part-select of an element of a packed array through a variable index, such as `m[i][7:0] = v`, is rejected ("Array index expressions must be constant here") and makes it stop on an internal assertion. | the 7 `gen/ch7/test_gen_wide_select_*_2state` tests |
| 20.9 | `$countbits` stops the run on an internal assertion (exit code 134), after the checks of `$countones`. | `ch20/test_countones_bits` |
| 6.16.12, 6.16.9 | `hextoa` of a negative int writes a minus sign and the digits of the magnitude (`-21524111` for 32'hDEADBEEF). As the inverse of `atohex`, which reads no sign, it has to write the hexadecimal digits of the value. | `ch6/test_string_hextoa` |
| 21.2.1.2 | A field width on `%h` pads with spaces (`[  ab]` for `%4h` of 8'hab); outside decimal, leading zeros are always displayed. | `ch21/test_display_format` |
| 16.3 | The pass statement of an immediate cover statement does not run when its expression is true (Verilator 5.052 does the same). | `ch16/test_assert_immed_2` |
| 30.7.1 | It ignores `PATHPULSE$`: a pulse on a module path that is narrower than the path delay is rejected, also when the reject and error limits of `PATHPULSE$` make it pass or turn it into x. | `ch30/test_specify_pulse_filtering`, `ch30/test_specify_pulsestyle_ondetect` |
| 36.3.2 | A VPI application registered as `$signed` or `$unsigned` does not replace the built-in function, whose result keeps the width of its argument instead of the width that the sizetf routine gives. | `ch36/test_vpi_systf_override_signed_width` |
| 37.3.5 | `vpi_get_value` on a system task argument with side effects, such as a function call or `k++`, gives the value from the call of the task each time instead of evaluating the argument again with its side effects. | `ch37/test_vpi_get_value_side_effects` |
| 37.20 | The vpiMemory and vpiMemoryWord relations give objects of the types vpiMemory and vpiMemoryWord instead of vpiRegArray and vpiReg, and the vpiIndex of a word counts from 0 instead of being its index in the range of the array. | `ch37/test_vpi_memory_word_objects` |
| 38.3 | `vpi_compare_objects` gives 0 for an argument that selects an element or a bit with a variable index, such as `mem[j]`, and the element or bit that the index selects. | `ch38/test_vpi_compare_objects_variable_select` |
| 38.22 | `vpi_handle_multi(vpiInterModPath, ...)` with ports at different levels of the hierarchy reports that it cannot insert the path and returns NULL. | `ch38/test_vpi_intermod_path_levels` |

### Illegal designs that it accepts

| Clause | Design | Tests |
| --- | --- | --- |
| 10.6.1 | A procedural assign statement to a part-select of a variable | `ch10/test_sched_procedural_assign_part_select` |
| 9.2.2.2 to 9.2.2.4 | A variable of always_ff, always_comb or always_latch written by another process, also through a function | `ch9/test_illegal_always_ff_other_writer`, `ch9/test_illegal_always_comb_other_writer`, `ch9/test_illegal_always_latch_other_writer`, `ch9/test_illegal_always_ff_written_via_function` |
| 6.5 | An input port declared as a variable and assigned by its module | `ch6/test_illegal_input_port_variable_assigned` |
| 25.5 | A modport that names a signal its interface does not declare | `ch25/test_illegal_modport_undeclared_name` |
| 8.10 | A static method that reads a non-static property | `ch8/test_illegal_static_method_uses_property` |
| 13.4 | fork-join or fork-join_any in a function | `ch13/test_illegal_function_fork_join`, `ch13/test_illegal_function_fork_join_any` |
| 6.20.5 | A parameter whose value uses a specify parameter | `ch6/test_illegal_parameter_from_specparam` |
| 33.4.1.2, 33.4.1.4, 33.4.2 | Two default liblist clauses, a cell clause with a library and a liblist, and an instance clause that names an instance inside the hierarchy of another config (it skips config declarations) | `ch33/test_illegal_config_two_default_liblists`, `ch33/test_illegal_config_cell_library_liblist`, `ch33/test_illegal_config_instance_inside_other_config` |
| 6.7.1 | A net type keyword followed directly by `reg` (`wire reg`) | `ch6/test_illegal_net_type_then_reg` |
| 23.10.4.2 | A defparam whose hierarchical name resolves to another parameter once the generate blocks are elaborated | `ch23/test_illegal_defparam_early_resolution` |
| 30.7.4.2 | A showcancelled declaration that names a path output after a module path to it | `ch30/test_illegal_showcancelled_after_path` |
| 24.3, 24.5 | A module that reads a variable of a program, and one that calls a task of a program | `ch24/test_illegal_program_signal_from_module`, `ch24/test_illegal_module_calls_program_task` |
| 12.8 | break inside a fork-join block that ends a loop around the block | `ch12/test_illegal_break_in_fork_to_outer_loop` |
| 29.3.4, 29.6 | A UDP table with two entries that give different outputs for the same inputs, and an entry with transitions on two inputs | `ch29/test_illegal_udp_conflicting_entries`, `ch29/test_illegal_udp_two_transitions_in_entry` |
| 31.4.4, 31.4.5, 31.4.6 | `$width` and `$period` whose reference event has no edge, and `$nochange` with an edge-control specifier (it skips timing checks) | `ch31/test_illegal_width_reference_not_edge`, `ch31/test_illegal_period_reference_not_edge`, `ch31/test_illegal_nochange_edge_control` |

It also rejects some illegal designs for another reason than their error:
it does not support ref ports or output arguments of functions, and it does
not parse the modport in an interface port of a module.

## Verilator 5.052

### Results

| Clause | What Verilator 5.052 does | Tests |
| --- | --- | --- |
| 20.10 | `$error` stops the run; it has to report the error and go on. The runner passes `+verilator+error+limit+1000000`, with which it goes on. | `ch20/test_error_does_not_end_run` (without that option) |
| 20.10, 9.2.3 | When `$fatal` ends the run, the final procedures do not run. | `ch20/test_fatal_runs_final_procedures` |
| 4.4.2.3, 21.2.2, 21.2.3 | At time 0, `$strobe` and `$monitor` show the values from before a write made after `#0` or by a nonblocking assignment; `$monitor` also misses changes of variables of an interface instance. | the 45 `gen/ch4/test_gen_sched_*_{strobe,monitor}_*` tests it does not match, `ch4/test_sched_strobe_after_zero_delays_and_nba`, `ch4/test_sched_monitor_once_per_time_step` |
| 4.9.1, 4.4.2.3 | After a second `#0`, it still shows the old value of a continuous assignment. | `ch4/test_sched_contassign_zero_delay` |
| 9.2.2.2.2 | `always @*` runs at time 0 and wakes for a change of a variable that it only reads in a called function. | `ch9/test_always_comb_vs_always_star` |
| 9.4.2 | Event controls wake once at time 0 although nothing changed. | `ch9/test_event_nested_struct_member`, `ch12/test_foreach_index_shadows_outer`, `ch16/test_deferred_assertion_disable_inner_scope` |
| 24.3.1 | A program's process sees the values from before the nonblocking updates of its time step (as Icarus Verilog 13.0). | `ch24/test_program_reactive_sees_nba`, `ch24/test_program_stimulus_after_clock_edge` |
| 24.7 | `$exit` called from a process of a module ends the simulation; it has to be ignored. | `ch24/test_exit_outside_program_ignored` |
| 24.7 | `$exit` called in a task of a program returns from the task, and the initial procedure goes on; it has to end every initial procedure of the program. | `ch24/test_program_exit_in_task` |
| 24.7 | `$exit` called in a forked thread of a program ends the whole simulation; it has to end only the initial procedures of that program. | `ch24/test_program_exit_from_fork` |
| 16.4, 16.4.2, 16.4.4 | It runs the action block of an observed deferred assertion at once, where the assertion is, instead of in the Reactive region, so a const ref argument reads the value from before the nonblocking update, and neither a flush point nor a disable statement can cancel the report. | `ch4/test_sched_deferred_action_arguments`, `ch16/test_deferred_assertion_forked_processes`, `ch16/test_deferred_assertion_disable_inner_scope` |
| 15.5.1 | A process waiting for an event triggered with `->>` does not wake. | `ch4/test_sched_nonblocking_event_trigger` |
| 26.3 | An explicit import of a name does not take precedence over a wildcard import that provides the same name from another package; the explicit import has to win. | `ch26/test_package_explicit_import_hides_wildcard` |
| 8.11, 6.23 | It rejects type(this) in a static method ("Cannot use 'this' in a static method"); type(this) names the type of the enclosing class anywhere in it. | `ch8/test_type_this` |
| 10.6.1, 4.9.2 | `assign` (procedural continuous) does not follow later changes of its right-hand side (as Icarus Verilog 13.0). | `ch4/test_sched_procedural_assign_deassign` |
| 11.5.2, 7.4.5 | An invalid address of a memory loses its upper bits, so another element is read and written. | `ch11/test_memory_invalid_address_2state` |
| 29.7, 29.8 | A sequential UDP instance with a delay changes its output before the delay has passed; with two delays it changes at the clock edge and uses neither. | `ch29/test_udp_initial_value_not_delayed`, `ch29/test_udp_instance_rise_fall_delay` |
| 14.16 | A synchronous drive of a clocking output on a net, here a 0 against a weak 1 and on a wand net, does not reach the net. | `ch14/test_clocking_output_net_driver` |
| 33.4.1.1, 33.5.4 | With a config whose design statement names two cells, it also makes another uninstantiated module a top-level module. | `ch33/test_config_design_two_tops` |
| 30 | It ignores the module path delays of specify blocks without an error, so outputs change without them. | the tests of chapter 30 with `iverilog@13.0` in `:oracle:`, such as `ch30/test_specify_path_rise_fall` |
| 31 | It skips timing checks without an error, so their notifiers never change. | the tests of chapter 31 with `:oracle: spec`, such as `ch31/test_timing_recrem_windows`, and `ch32/test_sdf_recrem_limits`, `ch32/test_sdf_timing_check_limits`, `ch32/test_sdf_separate_setup_hold`, `ch32/test_sdf_width_period_limits` |
| 20.4.2 | `$printtimescale` prints the name of the design element without parentheses. | `ch20/test_printtimescale_other_module`, `ch3/test_timeunit_with_precision` |
| 21.2.3 | `$monitoron` prints nothing. | `ch21/test_monitor_end_of_step` |
| 21.3.7 | `$ferror` puts "Undefined error: 0" in its string when there is no error. | `ch21/test_file_fflush_ferror` |
| 21.3.5 | After `$fseek` from the end of a file, it reads EOF and reports the wrong position. | `ch21/test_file_seek_tell_rewind` |
| 35.5.6, H.7.4 | shortreal arguments and results of imported functions are wrong (0.0). | `ch35/test_dpi_shortreal` |
| 18.5.12 | A guard of a constraint does not keep a null handle from being dereferenced. | `ch18/test_constraint_guard_null` |
| 18.6.3 | When randomization fails, it still calls post_randomize and changes the variables passed to `std::randomize`. | `ch18/test_randomize_failure_keeps_values` |
| 8.26.5 | A cast from one interface class handle to another fails. | `ch8/test_interface_class_cast` |
| 19.5, 19.5.7 | Values of a bin that do not survive the cast to the type of the coverpoint are not left out, and a sampled value is compared with the bins without being converted to the type of the coverpoint. | `ch19/test_cg_bins_value_resolution`, `ch19/test_cg_coverpoint_type_resolution` |
| 19.5.1 | A fixed number of bins is ignored, one bin per value is made. | `ch19/test_cg_fixed_count_bins` |
| 19.5.3 | An enum coverpoint gets the wrong number of automatic bins. | `ch19/test_cg_enum_auto_bins` |
| 19.5.5, 19.5.6 | Ignored and illegal values stay in the bins, also in automatic bins, and are counted; transition bins keep the sequences that contain an ignored or illegal transition. | `ch19/test_cg_ignore_bins`, `ch19/test_cg_illegal_bins_removed`, `ch19/test_cg_auto_bins_illegal_ignore`, `ch19/test_cg_excluded_transitions` |
| 19.7 | `at_least` is ignored: a bin is covered after one hit. | `ch19/test_cg_at_least` |
| 19.6, 19.11 | Coverage of a cross, and of a covergroup with weights, is the share of all bins, ignoring the weight option. | `ch19/test_cg_cross_coverage`, `ch19/test_cg_item_weighted_average` |
| 19.8 | Sampling goes on after `stop()`, and `get_coverage` sets both of its arguments to 0. | `ch19/test_cg_start_stop_counts` |
| 11.3.1 | It treats shortreal as real, so an expression with a shortreal operand and no real one is 64 bits wide instead of 32. | `ch11/test_real_operand_result_types` |
| 7.10.3, 13.5.2 | A reference to a queue element follows the position instead of the element: after the element is deleted, a write through the reference changes the element that took its place, and after an assignment to the whole queue it reads memory that is no longer the queue's. | `ch7/test_queue_reference_persistence` |
| 16.9.1 | It groups `x throughout y ##1 z` as `(x throughout y) ##1 z`; `##` has to bind more tightly than throughout. | `ch16/test_sequence_operator_precedence` |
| 20.4.1 | `$timeprecision` without an argument gives the simulation precision instead of that of the design element. | `ch20/test_timeunit_timeprecision_functions` |
| 20.7 | `$size` of a fixed-size dimension that follows a dynamic one gives 0. | `ch20/test_array_query_fixed_dimensions` |
| 21.2.1.6 | `%p` prints an int member in hexadecimal with `'h` and an enum member as a number instead of its name. | `ch21/test_format_p_struct` |
| 28.3.3, 28.10 | A pullup with a delay makes it stop with an internal error. As the error names the line of the pullup, the runner counts it as the rejection that the test asks for; `:oracle:` does not list `verilator@5.052`. | `ch28/test_illegal_pullup_delay` |
| 6.6.3 | A wand, wor, triand or trior net takes the value of one of its drivers instead of the AND or the OR of all of them (`1 & 0` gives 1, `0 \| 1` gives 0). | `ch6/test_net_wand`, `ch6/test_net_wor`, `ch6/test_net_triand`, `ch6/test_net_trior`, `ch6/test_edge_wor_wand`, `ch6/test_net_resolution`, `ch6/test_net_types_resolution` |
| 20.5 | `$shortrealtobits` gives 0 (other bits for 0.0001), and `$bitstoshortreal` gives 0.0. | `ch20/test_shortreal_ieee754`, `ch20/test_system_shortrealtobits`, `ch20/test_system_bitstoshortreal`, `ch20/test_real_bits_simple`, `ch20/test_real_literal_type`, `ch20/test_realtobits_bitstoreal`, `ch20/test_realtobits_corner_cases`, `ch20/test_math_special_values`, `ch20/test_type_conversion` |
| 20.8.2, 6.12 | A NaN, from a math function out of its domain or from `$bitstoreal`, compares equal to itself (`v != v` is false), although it prints as nan. A real is a C double, whose NaN is unequal to every value. | `ch20/test_math_special_values`, `ch20/test_math_advanced`, `ch20/test_math_hyperbolic_special_values`, `ch20/test_system_functions_edge`, `ch20/test_realtobits_bitstoreal` |
| 4.4.2.3, 4.5 | Right after `#0`, continuous assignments and always_comb blocks that a write before it woke still show their old values; the process resumes only when the Active region is empty. | `ch4/test_delta_cycle`, `ch4/test_ieee1800_2023_delta_convergence`, `ch9/test_always_comb_cascade_propagation` |
| 9.2.2.2, 4.4.2.3 | After `a = 1; b = 2; #0; a = 3; b = 4; #1`, an always_comb of `a + b` holds 3: it does not wake for the writes after `#0`. | `ch9/test_sensitivity_edge_cases` |
| 9.4.2.2 | An `always @*` block that writes a variable it also reads (a counter) stops the run with DIDNOTCONVERGE. Its own writes come while it runs, not while it waits, so they do not wake it again. | `ch9/test_implicit_event` |
| 21.3.4.3 | `$sscanf` ignores a field width (`%4d%4d` reads all of `12345678` into the first variable), and `%d` stops at an underscore, which it has to read as part of the number. | `ch21/test_scanf_comprehensive`, `ch21/test_numeric_edge_cases` |
| 6.16.9 | `atoi` reads a sign and skips leading spaces (`"-9876"` gives -9876, `"   42"` 42); it has to read only leading digits and underscores, and give 0 for both. | `ch6/test_string_atoi`, `ch6/test_string_atoi_2` |
| 5.7.1 | An unsized decimal number of 2147483648 or more is given only the bits of its magnitude and read as signed, so it turns negative: `1000000000000` gives -99511627776, and a longint of 2147483648 compares unequal to `2147483648`. | `ch6/test_int_types_edge_cases`, `ch11/test_ieee1800_2023_arithmetic_edge` |
| 11.6.1, 11.6.2 | `INT_MIN / -1` on int gives 0; the quotient, 2147483648, truncated to 32 bits is -2147483648. | `ch11/test_ieee1800_2023_arithmetic_edge` |
| 29.6 | A sequential UDP whose table toggles its output on a rising edge of the clock (a T flip-flop starting at 0) keeps the output at 0 after the edge. | `ch29/test_udp_seq` |
| 21.2.1.1 | `%E` and `%G` write a lower-case `e`. The real formats have the formatting of C, where they write `E`. | `ch21/test_format_advanced`, `ch21/test_format_float` |
| 16.3 | The pass statement of an immediate cover statement does not run when its expression is true (as Icarus Verilog 13.0). | `ch16/test_assert_immed_2` |
| 15.4.9 | It rejects a mailbox declared without a type parameter ("Class parameter type without default value"); such a mailbox is typeless. | `ch15/test_mailbox_typeless_try_type_check` |
| 16.4.3, 9.2.2.2.1 | A deferred assertion outside procedural code whose action blocks write variables stops the run with DIDNOTCONVERGE: the writes wake it again, although the expressions of action blocks do not add to its sensitivity. | `ch16/test_static_deferred_assertion_always_comb` |
| 16.12.7, 16.9.8 | `a ##[1:3] b \|=> c` passes when the consequent holds after one of the matches of the antecedent, also with `first_match`; it has to hold after each match, and with `first_match` after the first. | `ch16/test_first_match_antecedent` |
| 16.12.14 | `not (accept_on (k) ...)` passes when k aborts the evaluation; the abort makes the operand true, so the negation has to fail. | `ch16/test_property_abort_nesting` |
| 18.5.13.1 | Soft constraints of external constraint blocks rank in the order of the blocks instead of the order of their prototypes. | `ch18/test_soft_priority_layers` |
| 18.5.13.2 | `disable soft x` removes every soft constraint of lower priority, also those that do not name x. | `ch18/test_disable_soft_direct_reference` |
| 18.5.8, 18.11 | `randomize()` with arguments still randomizes the objects of the rand handles that it does not list, and applies their constraints. | `ch18/test_global_constraints_nested_inactive` |
| 18.5.7.1, 18.4 | With `randomize() with { q.size() == 3; }`, it sets `q[0]` to 3 and leaves `q` at its previous size; the size has to become 3. | `ch18/test_foreach_dynamic_multidim_constraint` |
| 18.11.1 | `randomize()` of an object with no random variables returns 1 also when its constraints do not hold; it has to return 0. | `ch18/test_randomize_checker_state_only` |
| 18.16 | The weight expression of a randcase item is evaluated twice each time the randcase runs; it may be evaluated at most once. | `ch18/test_randcase_weight_precision` |
| 35.6.1.1, H.7.6 | An unpacked array passed to a formal with the other range direction, `int up[0:3]` to `int a[3:0]`, reaches C in the order of the actual: C element 0 is `up[0]`. The formal is assigned from the actual left to right, so C element 0 has to be `a[0]`, which is `up[3]`. | `ch35/test_dpi_wysiwyg_formal_types` |
| 35.5.3 | When an export called from an import call chain returns, the chain keeps the scope that was set during the export instead of going back to the scope it had when the export was called. | `ch35/test_dpi_context_call_chain` |
| 38.6, 37.17 | `vpiType` of int, byte and longint variables is vpiLogicVar instead of vpiIntVar, vpiByteVar and vpiLongIntVar; a real variable has vpiScalar 1; and vpiTimeUnit and vpiTimePrecision give other values than the time units of the modules and the simulation. | `ch38/test_vpi_get_property_values` |
| 38.35 | `vpi_put_value_array` on a two-dimensional array writes the values from another element and in another order. | `ch38/test_vpi_put_value_array_order` |
| 38.36.1 | The time passed in the `s_cb_data` of a value change callback is 0 instead of the current time. | `ch38/test_vpi_release_handle_keeps_object` |

### Illegal designs that it accepts

| Clause | Design | Tests |
| --- | --- | --- |
| 10.6.1 | A procedural assign statement to a part-select of a variable | `ch10/test_sched_procedural_assign_part_select` |
| 9.2.2.2 to 9.2.2.4 | A variable of always_ff, always_comb or always_latch written by another process (it only warns, MULTIDRIVEN) | `ch9/test_illegal_always_ff_other_writer`, `ch9/test_illegal_always_comb_other_writer`, `ch9/test_illegal_always_latch_other_writer`, `ch9/test_illegal_always_ff_written_via_function` |
| 9.2.2.4 | always_ff with a delay or a second event control | `ch9/test_illegal_always_ff_delay`, `ch9/test_illegal_always_ff_two_event_controls` |
| 6.6.2 | A uwire net with two drivers | `ch6/test_illegal_uwire_two_drivers` |
| 6.5 | Continuous assignments to overlapping bits of a variable, and a variable driven by an output port and assigned elsewhere | `ch6/test_illegal_overlapping_continuous_assigns`, `ch6/test_illegal_output_port_variable_also_assigned` |
| 26.3 | A reference to a name that two wildcard imports provide | `ch26/test_illegal_wildcard_import_conflict` |
| 13.5.2 | A ref argument of a static task or function | `ch13/test_illegal_ref_in_static_task`, `ch13/test_illegal_ref_in_static_function` |
| 13.4 | A function with an output argument called in a continuous assignment | `ch13/test_illegal_function_in_continuous_assign_output` |
| 30.4.1, 30.4.5 | A module path from an output port, to an input port, or in parallel between vectors of different widths | `ch30/test_illegal_specify_path_from_output`, `ch30/test_illegal_specify_path_to_input`, `ch30/test_illegal_specify_parallel_width_mismatch` |
| 33.4.1.2, 33.4.1.4 | Two default liblist clauses, and a cell clause with a library and a liblist | `ch33/test_illegal_config_two_default_liblists`, `ch33/test_illegal_config_cell_library_liblist` |
| 6.7.1 | A net type keyword followed directly by `reg` (`wire reg`) | `ch6/test_illegal_net_type_then_reg` |
| 6.22.2, 6.22.3 | An assignment between variables of two anonymous unpacked struct types from different declarations, which are not equivalent | `ch6/test_illegal_anonymous_struct_not_equivalent` |
| 23.10.4.2 | A defparam whose hierarchical name resolves to another parameter once the generate blocks are elaborated | `ch23/test_illegal_defparam_early_resolution` |
| 8.26.4 | A class that implements a type parameter, or a forward typedef of an interface class | `ch8/test_illegal_class_implements_type_parameter`, `ch8/test_illegal_implements_forward_typedef` |
| 8.26.6.2 | An interface class that inherits the same typedef name from two interface classes and does not declare it | `ch8/test_illegal_interface_class_typedef_conflict` |
| 16.12.22 | The antecedent of `\|=>` is a sequence that can never match | `ch16/test_illegal_nonoverlapping_antecedent_no_match` |
| 20.7.1 | `$size` with a dimension number that names a queue dimension | `ch20/test_illegal_array_query_variable_dimension` |
| 20.10.1 | An elaboration-time `$error`, which it reports as the warning USERERROR; with `-Wno-fatal`, which the runner passes, the simulation starts | `ch20/test_illegal_elaboration_error_task` |
| 25.6, 30.7.4.2 | A ref port as a terminal of a module path, and a showcancelled declaration after the path (it ignores specify blocks) | `ch25/test_illegal_specify_ref_port_terminal`, `ch30/test_illegal_showcancelled_after_path` |
| 28.3.4 | An array of gate instances without a name | `ch28/test_illegal_unnamed_gate_array` |
| 3.14.2.2 | A timeunit declaration after another item of its module, and a repeated one that does not match the first | `ch3/test_illegal_timeunit_after_item`, `ch3/test_illegal_timeunit_mismatch` |
| 17.5, 17.7.1 | In a checker, a plain always procedure, a blocking assignment in always_ff and an assignment to a checker variable in an initial procedure; and a module that assigns a checker variable by its hierarchical name | `ch17/test_illegal_checker_plain_always`, `ch17/test_illegal_checker_always_ff_blocking`, `ch17/test_illegal_checker_variable_initial_assignment`, `ch17/test_illegal_checker_variable_hierarchical_write` |
| 18.5.9 | A solve-before constraint that names a property not declared rand | `ch18/test_illegal_solve_before_state_variable` |
| 24.3, 24.5 | A module that reads a variable of a program, and one that calls a task of a program | `ch24/test_illegal_program_signal_from_module`, `ch24/test_illegal_module_calls_program_task` |
| 29.3.1, 29.3.4, 29.7 | A UDP with a vector input, a UDP table with two entries that give different outputs for the same inputs, and a delay in the initial statement of a UDP | `ch29/test_illegal_udp_vector_port`, `ch29/test_illegal_udp_conflicting_entries`, `ch29/test_illegal_udp_initial_delay` |
| 31.4.4, 31.4.5, 31.4.6 | `$width` and `$period` whose reference event has no edge, `$width` with a notifier and no threshold, and `$nochange` with an edge-control specifier (it ignores specify blocks) | `ch31/test_illegal_width_reference_not_edge`, `ch31/test_illegal_period_reference_not_edge`, `ch31/test_illegal_width_notifier_without_threshold`, `ch31/test_illegal_nochange_edge_control` |
| 33.4 | A cell clause that binds a package name to another package | `ch33/test_illegal_config_package_binding` |
| 7.4.1 | A packed dimension on a type defined as real | `ch7/test_illegal_packed_array_of_real` |
| 9.2.2.2.2, 9.2.2.3 | A delay, an event control or fork-join in always_comb, and a delay in always_latch | `ch9/test_illegal_always_comb_delay`, `ch9/test_illegal_always_comb_event_control`, `ch9/test_illegal_always_comb_fork_join`, `ch9/test_illegal_always_latch_delay` |
| 8.19 | An assignment to a class constant with an initial value in the constructor, and an instance constant declared static | `ch8/test_illegal_global_constant_assigned_in_constructor`, `ch8/test_illegal_static_instance_constant` |
| 6.19 | An enum value given as a sized literal narrower than the base type | `ch6/test_illegal_enum_sized_literal_width` |
| 12.8 | break inside a fork-join block that ends a loop around the block | `ch12/test_illegal_break_in_fork_to_outer_loop` |
| 26.3 | A local declaration of a name that a wildcard import has already made visible | `ch26/test_illegal_local_declaration_after_import` |
| 8.20 | A pure virtual method declared :final | `ch8/test_illegal_final_pure_virtual` |
| 35.5.1.3, 35.5.4 | An imported task declared pure | `ch35/test_illegal_dpi_pure_import_task` |

## Cases added by the 2026-10-22 depth extension

These cases strengthen clauses that previously had one directly citing test.
The expected results were derived before the release runs. Unsupported
constructs are described in the source comments rather than treated as
independent oracle confirmations. The following observable differences remain:

- Icarus 13.0 does not wake a wait on queue size when the final element is
  popped (7.10.2.7):
  [test_queue_size_wait_after_pop](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch7/test_queue_size_wait_after_pop.sv).
- Icarus 13.0 constructs the derived object through a typed constructor but
  calls the base virtual method through the base handle (8.8, 8.20):
  [test_typed_constructor_into_base_handle](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch8/test_typed_constructor_into_base_handle.sv).
- Icarus 13.0 keeps source macro definitions after `undefineall` (22.5.3):
  [test_undefineall_clears_nested_macro_expansion](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch22/test_undefineall_clears_nested_macro_expansion.sv).
- Icarus 13.0 accepts a value argument to the argumentless `$stacktrace`
  call (20.17.2):
  [test_illegal_stacktrace_argument](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch20/test_illegal_stacktrace_argument.sv).
- Both releases propagate a program continuous output before a module NBA
  reaction to its input has completed (24.3.2):
  [test_program_output_after_module_nba_chain](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch24/test_program_output_after_module_nba_chain.sv).
- The 5.052 release orders signed associative keys as unsigned values
  across zero (7.8.4):
  [test_assoc_signed_boundary_order](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch7/test_assoc_signed_boundary_order.sv).
- The 5.052 release accepts an associative key type containing a real
  member (7.8.5):
  [test_illegal_assoc_real_member_key](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch7/test_illegal_assoc_real_member_key.sv).
- The 5.052 release expands an inner string concatenation into two queue
  elements instead of keeping it as one string item (10.10.3):
  [test_unpacked_concat_typed_array_and_string_item](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch10/test_unpacked_concat_typed_array_and_string_item.sv).
- The 5.052 release loses the prototype default when an out-of-block
  method definition legally omits it (8.24):
  [test_extern_method_scoped_return_type](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch8/test_extern_method_scoped_return_type.sv).
- The 5.052 release runs the mixed event sensitivity processes at time zero
  as well as at the four later input changes (9.4.2.1, 6.8):
  [test_event_or_mixed_comma_forms](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch9/test_event_or_mixed_comma_forms.sv).
- The 5.052 release accepts a checker covergroup referencing a formal
  whose actual is constant (17.6):
  [test_illegal_checker_covergroup_constant_actual](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch17/test_illegal_checker_covergroup_constant_actual.sv).
- The 5.052 release observes a different position after seeking with a
  pushed-back character and does not clear the error text after a successful
  I/O operation (21.3.5, 21.3.7):
  [test_fseek_cancels_ungetc_and_clears_error](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch21/test_fseek_cancels_ungetc_and_clears_error.sv).
- The 5.052 release prints the sampled value for the live reference in an
  assertion pass action after the NBA update (4.4.2.5, 16.5.1):
  [test_preponed_sample_observed_before_action](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch4/test_preponed_sample_observed_before_action.sv).
- LABEL annotation is unavailable in Icarus 13.0; the 5.052 release ignores
  SDF annotation, including the new dependent label expression and pulse
  boundary cases (32.4.3, 32.7):
  [test_sdf_label_recomputes_delay_expression](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch32/test_sdf_label_recomputes_delay_expression.sv),
  [test_sdf_pulse_limit_near_delay_boundary](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tests/ch32/test_sdf_pulse_limit_near_delay_boundary.sv).

## Cases added after the 2026-10-23 expression review

- IEEE 11.7, 6.24.1 and 20.7: Icarus 13.0 stops with a segmentation fault
  compiling array queries on cast expressions in
  `ch11/test_signed_system_cast_shape_and_value` and
  `ch6/test_size_cast_intermediate_context`. The queries are legal on
  fixed-size integral expressions; Verilator 5.052 matches both tests.
- IEEE 11.3.5: Icarus 13.0 evaluates a forbidden operand and executes its
  `$fatal` in `ch11/test_short_circuit_suppresses_fatal_operand`.
  The selected operands require no call, side effect or run-time error.
  Verilator 5.052 skips all five calls and matches the expected output.
- IEEE 11.3.1 and 6.12: in
  `ch11/test_shortreal_result_and_condition_types`, Icarus 13.0 reports
  arithmetic expression widths of 1 instead of 32 for shortreal and 64 for
  a mixed-real result. Verilator 5.052 instead reports 64 for shortreal
  arithmetic and branches because it promotes shortreal to real. The
  expected output retains the standard's 32-bit shortreal requirements;
  neither release is recorded as an oracle for this test.

The new `ch11/test_real_boolean_results_without_shortreal` isolates the
one-bit real logical/relational/inside results. It matches Verilator 5.052
without requiring shortreal support. Icarus 13.0 rejects `inside` as
unsupported; that compilation failure is not evidence of execution success.

## Cases added after the 2026-10-23 associative array review

The new cases retain expectations derived from IEEE 1800-2023. Verilator
5.052 (2026-09-05, vUNKNOWN-built20260905) matches eight of the fifteen
cases with initialization seeds 1 and 73. The following seven differences
remain; none is counted as execution success:

- IEEE 7.9.3–7.9.7: `ch7/test_assoc_method_expression_types` reports
  `logic[31:0]` for `exists()` and `integer` for first/last/next/prev,
  instead of `int` for each method expression. The separate
  `ch7/test_assoc_count_expression_types` matches num/size types and counts.
- IEEE 7.9.6: `ch7/test_assoc_traversal_gaps_and_preserved_keys` returns
  status 0 and unchanged key 20 for `next()` from an absent key between
  present keys 10 and 30. It must return 1 and key 30.
- IEEE 7.8.7: `ch7/test_assoc_ref_allocates_before_callee_write` is rejected
  with “Function/task ref argument is not of allowed type” for the
  associative element actual. The test observes allocation before any
  callee read or write; the unsupported call does not prove allocation.
- IEEE 7.8.4: `ch7/test_assoc_signed_and_unsigned_key_order` visits signed
  8-bit key 0 before -128. Signed ordering must be -128, -1, 0.
- IEEE 7.8.4: `ch7/test_assoc_integral_index_cast_context` evaluates
  `4'hf + 4'h1` as key 0, instead of key 16 in the 8-bit index cast context.
- IEEE 7.8.6 and Table 7-1: `ch7/test_assoc_missing_read_reports_diagnostic`
  reads a known initialized bit pattern instead of `xxxxxxxx` from a
  missing `integer` element (for example, `f7df13e4` with seed 1).
  This output mismatch alone does not establish the separate warning check.
- IEEE 7.8.6: `ch7/test_assoc_invalid_write_reports_diagnostic` creates a
  second entry for a key containing X. The write must be ignored with a
  warning, leaving the original single entry.

Icarus Verilog 13.0 stable (v13_0-dirty) fails compilation of all fifteen
cases because of unsupported associative arrays or unpacked structs.
These actual compile attempts are recorded as known differences, not passes.

See [the test addition report](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/associative-gap-tests-20261023.md) for all
inputs, mutation checks, result snapshots and coverage changes. The original
fifteen-case runs and the later one-case wildcard/count refinements are kept
as separate snapshots; partial successes are not merged into one run.

## Cases added by the 2026-10-23 header and VPI model tests

The new tests of the normative C headers (Annexes I, K, L and M) compare
the constants, types, include guards and declarations of the headers that a
simulator provides with those the annexes give. One header defines
something differently from the standard:

- IEEE H.10.1.2, I.3: the svdpi.h of Verilator 5.052 defines `SV_MASK(N)`
  as `~(0xffffffffU << (N))`, an unsigned int, where the standard gives
  `~(-1 << (N))`, an int; the low bits it sets are the same.
  `ch35/test_svdpi_h_sv_mask` prints 0 for the text and the type of the
  macro, so `:oracle:` lists no simulator.

The other differences these tests show are left out as unsupported
features, as above. Icarus Verilog 13.0's vpi_user.h and sv_vpi_user.h
define 218 of the 855 constants of K.2 and M.2, all with the values the
annexes give, and lack most of the declarations of K.2 and M.2, so the
constant tests miss lines and the declaration tests do not compile with it.
Neither release provides vpi_compatibility.h (Verilator's copy of vpi_user.h
has the line that includes it commented out), so the six
`ch36/test_vpi_compatibility_h_*` tests show the routine names unmapped.
The 24 new VPI tests of clause 37 (`ch37/test_vpi_*` added the same day)
use constants that Icarus Verilog 13.0's headers lack and system tasks
registered with vpi_register_systf, which Verilator 5.052 cannot call; one
of them matches Icarus Verilog 13.0 and the others have `:oracle: spec`.

## Cases added by the 2026-10-24 keyword tests

The generated tests of `generators/keywords.py` declare each reserved
keyword as a variable name inside a `begin_keywords` region of a version
that reserves it. Both releases reject 493 of the 496 at the declaration.

- IEEE 5.6, Annex B, 22.14.7: Verilator 5.052 accepts `global` as a
  variable name under `begin_keywords "1800-2023"` and
  `begin_keywords "1800-2009"`, which reserve it.
  `gen/ch5/test_gen_kw_2023_global`, `gen/ch22/test_gen_kw_1800_2009_global`
- IEEE 5.6, 22.14.2: Verilator 5.052 accepts `ifnone` as a variable name
  under `begin_keywords "1364-1995"`, which reserves it.
  `gen/ch22/test_gen_kw_1364_1995_ifnone`
- IEEE 22.14: Icarus Verilog 13.0 does not know the version strings
  "1800-2017" and "1800-2023": it prints that it ignores them and keeps its
  default keyword set, where 22.14 lists both as standard versions and makes
  an unrecognized one an error. Its default set reserves every keyword of
  Annex B, so the 248 `gen/ch5/test_gen_kw_2023_*` tests still match it.
