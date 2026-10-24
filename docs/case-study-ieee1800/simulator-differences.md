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
  [test_queue_size_wait_after_pop](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch7/test_queue_size_wait_after_pop.sv).
- Icarus 13.0 constructs the derived object through a typed constructor but
  calls the base virtual method through the base handle (8.8, 8.20):
  [test_typed_constructor_into_base_handle](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch8/test_typed_constructor_into_base_handle.sv).
- Icarus 13.0 keeps source macro definitions after `undefineall` (22.5.3):
  [test_undefineall_clears_nested_macro_expansion](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch22/test_undefineall_clears_nested_macro_expansion.sv).
- Icarus 13.0 accepts a value argument to the argumentless `$stacktrace`
  call (20.17.2):
  [test_illegal_stacktrace_argument](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch20/test_illegal_stacktrace_argument.sv).
- Both releases propagate a program continuous output before a module NBA
  reaction to its input has completed (24.3.2):
  [test_program_output_after_module_nba_chain](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch24/test_program_output_after_module_nba_chain.sv).
- The 5.052 release orders signed associative keys as unsigned values
  across zero (7.8.4):
  [test_assoc_signed_boundary_order](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch7/test_assoc_signed_boundary_order.sv).
- The 5.052 release accepts an associative key type containing a real
  member (7.8.5):
  [test_illegal_assoc_real_member_key](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch7/test_illegal_assoc_real_member_key.sv).
- The 5.052 release expands an inner string concatenation into two queue
  elements instead of keeping it as one string item (10.10.3):
  [test_unpacked_concat_typed_array_and_string_item](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch10/test_unpacked_concat_typed_array_and_string_item.sv).
- The 5.052 release loses the prototype default when an out-of-block
  method definition legally omits it (8.24):
  [test_extern_method_scoped_return_type](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch8/test_extern_method_scoped_return_type.sv).
- The 5.052 release runs the mixed event sensitivity processes at time zero
  as well as at the four later input changes (9.4.2.1, 6.8):
  [test_event_or_mixed_comma_forms](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch9/test_event_or_mixed_comma_forms.sv).
- The 5.052 release accepts a checker covergroup referencing a formal
  whose actual is constant (17.6):
  [test_illegal_checker_covergroup_constant_actual](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch17/test_illegal_checker_covergroup_constant_actual.sv).
- The 5.052 release observes a different position after seeking with a
  pushed-back character and does not clear the error text after a successful
  I/O operation (21.3.5, 21.3.7):
  [test_fseek_cancels_ungetc_and_clears_error](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch21/test_fseek_cancels_ungetc_and_clears_error.sv).
- The 5.052 release prints the sampled value for the live reference in an
  assertion pass action after the NBA update (4.4.2.5, 16.5.1):
  [test_preponed_sample_observed_before_action](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch4/test_preponed_sample_observed_before_action.sv).
- LABEL annotation is unavailable in Icarus 13.0; the 5.052 release ignores
  SDF annotation, including the new dependent label expression and pulse
  boundary cases (32.4.3, 32.7):
  [test_sdf_label_recomputes_delay_expression](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch32/test_sdf_label_recomputes_delay_expression.sv),
  [test_sdf_pulse_limit_near_delay_boundary](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/tests/ch32/test_sdf_pulse_limit_near_delay_boundary.sv).

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

See [the test addition report](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/docs/associative-gap-tests-20261023.md) for all
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

## Cases added by the 2026-10-24 gap tests

The tests written for open requirements (see the [result report](gap-tests-20261024.md)) show the
following differences, taken from the notes their writers kept and checked by their
independent reviewers. As above, constructs that a release rejects or does not support,
internal faults, missing header constants and VPI relations it does not model, and
Verilator's two-state values are left out.

### Icarus Verilog 13.0: results

| Clause | What it does | Tests |
| --- | --- | --- |
| 6.16 (Table 6-9) | `s_b < "ab"` with `string s_b = "b"` gives 1 (and `s_b > "ab"` also gives 1). | `ch6/test_string_comparison_operators_and_literals` |
| 6.11.3, 6.8 | `integer unsigned u = '1;` displays -1 with `%0d`: the unsigned keyword on integer is ignored. | `ch6/test_integer_types_state_and_signing` |
| 6.12, 6.13 | A shortreal initialized to `1.0 + 2.0 ** -30` compares unequal to 1.0 (the value is kept at double precision), although `$shortrealtobits` of it gives 3f800000. | `ch6/test_shortreal_ieee754_single` |
| 6.10, 23.2.2.1, 22.8 | Under `` `default_nettype wand ``, the implicit net of a non-ANSI port with only a port declaration (`output [3:0] y;`) is a wire: two drivers 1101 and 0110 resolve to x1xx. (Implicit nets from continuous assignments, port connections and gate terminals do get wand: `ch6/test_implicit_net_scope_and_lookup` matches.) | `ch6/test_implicit_port_expression_nets` |
| 6.16.10 | `s[i].atoreal()` on the elements of a string array returns 0.0 for every element (`"2.5e3xyz"`, `"3.75"`, ...), and the empty element prints as a space. | `ch6/test_string_atoreal_scan_rules` |
| 6.19, 6.24.1 | Evaluates the enum value expression `4'hf + 4'h1` of a `bit [4:0]` enum with the 4-bit width of its operands (Q=0, R=1) instead of in the context of a cast to the 5-bit base type (Q=16, R=17). | `ch6/test_enum_encoding_cast_to_base` |
| 6.16, 6.20 | A `parameter string S` initialized with a literal that contains NUL characters (`"\0"`) keeps them: `S.len()` is 7 instead of 3, the length of the string with the NUL characters removed. | `ch6/test_param_literal_initializers_follow_type` |
| 7.3.1, 6.11.2 | Reading the 2-state member `bit [7:0] b2` of a packed union that also has a 4-state member returns the stored x/z bits unchanged (`b2=1x0z10x1`, `$isunknown(m.b2)=1`, `b2+1=xxxxxxxx`) instead of converting them to 0 (`10001001`, 0, `10001010`); the initial read of b2 also gives `xxxxxxxx` instead of `00000000`. | `ch7/test_packed_union_mixed_two_four_state` |
| 7.4.4 | For `typedef tri_t row_t [0:3]; row_t tab [0:1];` the unpacked dimension of the typedef becomes the slowest one (`$size(tab,1)=4`, `$size(tab,2)=2`, `tab[1][2]` reported out of bounds), and the subarray assignment `one_row = tab[1]` is rejected. The dimensions from the typedef vary faster than those of the declaration, so tab is [0:1][0:3]. | `ch7/test_multidim_typedef_stages_and_shared_declaration` |
| 7.10.1 | A queue slice `q[a:b]` with variable bounds yields the whole queue (`size=5: 10 20 30 40 50`) for every pair of bounds. | `ch7/test_queue_slice_bounds_clip_and_empty` |
| 11.4.7, 11.3.5 | Evaluates the second operand of `->` when the first operand is false: `lhs(1'b0) -> rhs(1'b0)` calls rhs (`nr=1`). For `&&` and `->`, a logically false first operand means the second operand shall not be evaluated. | `ch11/test_logical_operands_evaluated_once_and_unknown_left` |
| 11.4.1, 11.4.10 | `arr[k] >>>= 2` on an element of `int arr[4]` holding -16 gives 1073741820 (zeros shifted in), while `x >>>= 2` on an int variable and `arr[1] = arr[1] >>> 2` give -4. The compound assignment has the meaning of the blocking assignment with the binary operator, and >>> of a signed operand fills with the sign bit. | `ch11/test_compound_assignment_index_evaluated_once` |
| 11.5.1 | A bit-select of the 2-state `bit [7:0] b` with an out-of-range index (`b[i8]`, i8 = 8) or an x index reads x, and `q4 = b[i9 +: 4]` (wholly out of range) leaves x in the 2-state `bit [3:0] q4` (`xxxx`). An invalid select of a 2-state value reads 0. | `ch11/test_vector_select_declared_bounds_direction_and_invalid` |
| 26.3 | `localparam int k_first = k;` written before `import lp::*;` gives `lp::k` (5) when `k` is referenced again after the import; with no later reference it gives the compilation-unit `k` (100). Only wildcard candidates before the reference may be used, so it has to be 100. | `ch26/test_package_lookup_reference_point` |
| 28.6 | notif0 and notif1 with data 0 or 1 and a control that is x or z show StX; Table 28-5 gives H (data 0) and L (data 1), shown as StH and StL. | `ch28/test_notif_gate_truth_table_all_inputs` |
| 28.7, 28.14 | rnmos and rpmos that are the only driver of a net show their output with strong strength (St0, St1, StX) and StX where Table 28-6 gives L or H; the standard requires the strong data to be reduced to pull (Pu0, Pu1, PuX, PuL, PuH). With a second, z driver on the net rnmos shows the right values, rpmos still not. nmos and pmos match. | `ch28/test_mos_switch_truth_tables` |
| 28.9, 28.14 | rcmos passes strong data with strong strength (St0, St1) where 28.14 requires pull strength, as an rnmos/rpmos pair on one net shows (the known rcmos deviation, here compared with that pair). | `ch28/test_rcmos_switch_rnmos_rpmos_equivalence` |
| 28.8 | A tranif0 with two delays (d1, d2) uses d1 when its control rises to 1 (the switch turns off) and d2 when the control falls to 0 (the switch turns on); 28.8 makes the first delay the turn-on delay and the second the turn-off delay. tranif1 matches (tests/ch28/test_pass_switch_control_delay_forms.sv). | `ch28/test_tranif0_control_turn_on_off_delays` |
| 28.12.4 | On wand and wor with drivers of ambiguous strength it gives St0, St1, St0, StX instead of 650, 65X, 56X, 56X (the known deviation that it ignores driver strengths on wired nets). | `ch28/test_wired_logic_ambiguous_strength_combinations` |
| 30.5.1 | A negative module path delay (a specparam of -3, or 1 - 6) is not treated as zero: the output change that should come without delay never appears in the run. | `ch30/test_specify_negative_path_delay` |
| 30.7.4.2 | Ignores showcancelled and pulsestyle_ondetect: the negative pulse leaves the output at 1 instead of x from 15 (on-event) or 12 (on-detect) to 17. | `ch30/test_showcancelled_negative_pulse_x` |
| 32.3 | Reports an IOPATH entry without a matching module path as "SDF ERROR: Unable to match ModPath" instead of a warning; it does annotate the other entries. | `ch32/test_sdf_unannotatable_entry_warning` |
| 36.5, 36.8.1 | A vpiSizedFunc whose sizetf gives 12 returns 32 bits ("function result: 00000f01"); Icarus takes the width from a .sft file at compile time, not from sizetf. All other lines match. | `ch36/test_vpi_systf_task_function_places` |
| 37.39 | vpi_get(vpiDirection) of a path term returns a value other than vpiInput/vpiOutput, and vpi_handle(vpiModPath, path_term) returns NULL; vpiModule of a path and vpi_get_delays/vpi_put_delays of a path match. | `ch37/test_vpi_mod_path_relations_delays` |
| 37.41, 13.4 | On functions, vpiFuncType gives vpiSizedFunc for integer and vpiSizedSignedFunc for time, which 37.41 does not give for them. | `ch37/test_vpi_function_decl_type_range` |
| 38.3 | vpi_compare_objects returns 1 only for the same handle (also for mem[j] with j out of range) and 0 for distinct handles to the same element (mem[j] vs mem[k] with j==k, mem[j] vs vpi_handle_by_index(mem,0)) | `ch38/test_vpi_compare_objects_current_object` |
| 38.15, K.2 | vpi_user.h declares s_vpi_vecval aval and bval as PLI_INT32 instead of PLI_UINT32 (Figure 38-8) | `ch38/test_vpi_value_time_delay_structures` |
| 38.34 | vpiInertialDelay and vpiTransportDelay remove no scheduled event (all three modes behave as vpiPureTransportDelay) | `ch38/test_vpi_put_value_delay_modes_queue` |
| 38.19 | vpi_handle_by_index(scalar, 0) returns a handle (s[0]) although a bit-select of a scalar is illegal (11.5.1), so 38.19 requires NULL; unused variables are also left out of the VPI model. | `ch38/test_vpi_handle_by_name_scope_index` |
| 38.27, 38.25 | vpi_mcd_open of a file that vpi_mcd_open or $fopen already opened gives a new descriptor instead of the existing one; vpi_mcd_flush of a channel with no open file returns 0 (it calls fflush(NULL)) | `ch38/test_vpi_mcd_open_reuse` |

### Icarus Verilog 13.0: illegal designs that it accepts

| Clause | What it does | Tests |
| --- | --- | --- |
| 6.21 | Accepts `da[1] <= 2;`, a nonblocking assignment to an element of a dynamic array. | `ch6/test_illegal_nonblocking_to_dynamic_array_element` |
| 7.4.1 | Accepts `bit [8] octet;`, a packed dimension given as a single size, without an error. A packed dimension needs a `[ constant_expression : constant_expression ]` range. | `ch7/test_illegal_packed_dimension_single_size` |
| 8.17 | Accepts an explicit `super.new(3)` in a subclass whose extends clause already gives the constructor arguments (`extends base_c(5)`). | `ch8/test_illegal_super_new_with_extends_arguments` |
| 29.7 | Accepts a UDP initial statement that assigns an input instead of the output reg. | `ch29/test_illegal_udp_initial_assigns_input` |
| 30.4.2, 30.4.5, 30.4.6 | Accepts a parallel module path with a list of sources `(a, b => y)` or of destinations `(b => y, z)`; Syntax 30-3 gives a parallel connection one input and one output terminal, and 30.4.5/30.4.6 require a full connection for several sources or destinations. (Verilator 5.052 accepts them too; it does not check specify paths.) | `ch30/test_illegal_specify_parallel_multiple_sources`, `ch30/test_illegal_specify_parallel_multiple_destinations` |

### Verilator 5.052: results

| Clause | What it does | Tests |
| --- | --- | --- |
| 6.16.3 | Gives `getc()` the unsigned type `bit[7:0]` (`$typename` prints `bit[7:0]`, and `s.getc(64'h1_0000_0002)` on the character 8'he9 prints 233) instead of the signed `byte` of its prototype (`byte`, -23). | `ch6/test_string_getc_index_rules` |
| 6.16.9 | atoi/atohex/atooct skip leading white space and parse a sign like C strtol: `" 12".atoi()=12`, `"-12".atoi()=-12`, `"+12".atoi()=12`, `"-ff".atohex()=-255`, `"-7".atooct()=-7`. The scan takes only leading digits and underscores and does not parse a sign, so all of these are 0. | `ch6/test_string_ato_integer_scan_rules` |
| 6.19.5.3, 6.19.5.4 | For a value that is not a member (`t_t'(7)` of {A=1,B=2,C=3}), next() returns A, prev() returns B and next(2) returns B, and for `l_t'(3'd6)` of a logic [2:0] enum next() and prev() return P (001); the standard returns the default initial value of the enum, 0 for the int base and xxx for the logic base. (For the default value 0 itself, prev() gives 0.) | `ch6/test_enum_next_prev_from_non_member` |
| 6.19.5.5, 20.6.1 | `$typename(c.num())` prints `bit[31:0]` instead of `int`, the return type of the num() prototype (the value 3 and the signed comparison `c.num() - 5 < 0` are right). | `ch6/test_enum_num_name_result_types` |
| 6.22.1 f, 7.4.2 | `type(fa) == type(fd)` for `int fa [0:3]` and `int fd [4]` gives 0; `[4]` declares the bounds [0:3] (https://github.com/kurochan001/kirimasim-tests/blob/b13204c/docs/7.4.2), so the fixed-size arrays have the same bounds and matching elements and match (1). | `ch6/test_type_matching_rules_by_type_compare` |
| 6.24.1, 20.6.1 | `$typename(signed'(b))` for `bit [3:0] b` and `$typename(unsigned'(bs))` for `bit signed [3:0] bs` give `logic[3:0]`: the signing cast of a 2-state operand becomes a 4-state vector, where its elements shall be bit (the size casts `8'(b)` give `bit[7:0]` as required). Its `$typename` also leaves out `signed` (`$typename(bit signed [3:0])` is `bit[3:0]`). Icarus Verilog 13.0 has no `$typename` of a data type. | `ch6/test_cast_size_sign_keep_state_domain` |
| 20.5, 6.24.1 | `$shortrealtobits` returns the 64-bit double precision pattern (`$shortrealtobits(n)` for -2.5 prints `c004000000000000`, and the 32-bit variable assigned `$shortrealtobits(3.375)` gets 0) instead of the 32-bit single precision pattern (`c0200000`, `40580000`). | `ch6/test_cast_shortreal_round_vs_bit_pattern` |
| 7.4.1, 6.22.1 e, 6.23 | A type-reference comparison between an integer type with a predefined width and its matching vector type gives 0 (`type(byte) == type(bit signed [7:0])`, also with a typedef of that vector, and likewise for shortint, int, longint, integer, time), while `type(int) == type(int)` gives 1. The standard makes them matching types, so the comparisons are 1. | `ch7/test_integer_atom_types_match_vector_types` |
| 7.4.5 Table 7-1 | Reading a fixed unpacked array of real, shortreal, string, class, interface class or virtual interface elements with an out-of-bounds index (7 for [0:3]) or an index with an x bit returns a stored element value (1.5, 2.5, "full", non-null handles) instead of 0.0, "" and null. The C++ build also fails on reads/`== null` comparisons of an event array element (`cannot convert 'VlEvent' to 'IData'`). | `ch7/test_array_invalid_index_read_handles_real_string` |
| 7.4.5 Table 7-1 | Reading `[0:1]` arrays of queues, dynamic arrays, associative arrays, fixed-size arrays, unpacked structures and unpacked unions with index 5 or 2'bx0 returns the stored element (sizes 2/3/1, 1,2,3, the stored structure and union) instead of empty arrays, arrays of 'x / '0, a structure of member defaults (with the initial assignment c = 9) and 'x for the first union member. | `ch7/test_array_invalid_index_read_aggregates` |
| 7.4.5 Table 7-1 | Reading a `chandle ch [0:3]` whose elements C set to non-null pointers with index 7 or 2'b1x returns a non-null chandle (`null=0`) instead of null. | `ch7/test_array_invalid_index_read_chandle` |
| 7.5.1, 13.5.2 | After `d = new[3](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/docs/d)` outdates a task's `ref int r` to `d[1]`, the task's later write `r = 99` changes the new array (`t=4: 5 99 7`) instead of only the outdated element (`5 6 7`). | `ch7/test_dynamic_array_new_discards_data_and_references` |
| 7.10.1 | For q = {10,20,30,40,50}: `q[5:5]` yields `{50}` instead of `{}`, `q[-1:-1]` yields the whole queue instead of `{}`, and `q[1:3'b0z1]` yields one element instead of `{}` (a bound with a z bit). In-range, clipped and reversed slices are right. | `ch7/test_queue_slice_bounds_clip_and_empty` |
| 7.10.5 | `insert(1, 9)` on a full `int bq[$:2]` grows it to four elements (`0 9 1 2`) instead of dropping the element pushed past index 2 (`0 9 1`); push_back, push_front and the write to [$+1] are bounded correctly. | `ch7/test_bounded_queue_methods_discard_beyond_bound` |
| 7.10.5 | Assigning a five-element unbounded queue to `int bq[$:2]` keeps two elements (`20 21`) instead of three (`20 21 22`); the concatenation assignments are bounded correctly. | `ch7/test_bounded_queue_assign_discards_beyond_bound` |
| 7.12.1, 7.8.4 | For `int dn [4:1] = '{7,0,9,5}`, find_first/find_first_index give 5 at 0 and find_last/find_last_index give 7 at 3 (expected 7 at 4 and 5 at 1); for `up [1:4]` the indices are 0 and 3 (expected 1 and 4). For an `int aa[int]` with keys -5, 0, 3, 10, find_first/find_last follow unsigned key order (8 at 3, 6 at -5) instead of the first()/last() order (6 at -5, 4 at 10). | `ch7/test_array_locator_first_last_by_range_and_min_tie` |
| 7.12.2 | `sort()` and `rsort()` without a with clause on `int b[$] = '{3, -1, 2}` order the elements as unsigned values (`2 3 -1` and `-1 3 2`) instead of by the signed int relational operators (`-1 2 3` and `3 2 -1`). With a with clause, and on strings and structures, the results are right. | `ch7/test_array_ordering_methods_with_and_iterator` |
| 7.12.3 | The width of a reduction result does not follow the element type or the with expression: `$bits(b.sum(v) with (int'(v)))` is 8 (expected 32), `lo.sum with (item[3:0])` on {8'h0f, 8'h0e} gives 29 with `$bits` 8 (expected 13 and 4), and `ba.sum()` on a `bit ba[4] = '{1,1,1,0}` gives 3 (expected 1, a 1-bit result). The values of the int'() sums are right. | `ch7/test_array_reduction_result_type_and_with_width` |
| 8.23 | In a derived class that declares its own non-virtual `f`, the call `base_c::f()` runs the derived `f` (sum 224) instead of the method of base_c (sum 124). `base_c::pv`, `base_c::pub` and `base_c::ps` select the base members correctly. | `ch8/test_class_scope_base_members_from_derived` |
| 11.4.6 | `!=?` of two handles to different objects (interface class handles `i1 !=? i3`, also a plain class `b1 !=? b2`) and of two different chandles (`c1 !=? c2`) gives 0. For class, interface class and chandle operands the wildcard operators are the same as == and !=, so the result is 1. | `ch11/test_equality_class_interface_chandle_handles` |
| 11.4.12.1 | The operand of a replication with a zero multiplier is not evaluated: `{{Z{next()}}, 4'hf}` with Z = 0 leaves the call count at 0. The operands of a replication are evaluated exactly once, even when the multiplier is zero. | `ch11/test_concatenation_pattern_string_operand_and_replication_once` |
| 11.2.1, 20.4.1, 20.5 | `$shortrealtobits(0.5)` in a localparam gives 00000000, and `$bitstoshortreal` there gives 0.0. | `ch11/test_constant_system_function_calls_at_elaboration` |
| 20.2 | After `$finish(0)` the calling procedure goes on and prints `10: after $finish` before the run ends. | `ch20/test_finish_ends_simulation` |
| 20.2, 24.7 | `$exit()` from the first program ends the whole simulation at once (at 5), after the rest of the calling procedure has run (`5: p_first after $exit`) | `ch20/test_exit_waits_for_programs` |
| 19.5, 19.5.2, 19.7 (already listed for `ch19/test_cg_at_least`) | `at_least` is ignored: each bin is covered after its first hit (`value bin after 0, 1, 2: 100`) | `ch19/test_cg_bin_hit_counts` |
| 27.5, 23.3.1 | Without `--top-module`, it elaborates module `self_only`, which is instantiated only by itself inside a conditional generate, as a top-level module and runs its initial procedure ("self_only elaborated with D=2"). A module that contains an instance of itself is not a top-level module. | `ch27/test_generate_recursive_module` |
| 26.6 | A package with `export xt_base::*;` written before `import xt_base::w;` does not make `w` visible: a module that imports `xt_early::w` gets the compilation-unit `w` (200) instead of `xt_base::w` (2). An export may precede its corresponding import. | `ch26/test_package_export_transitivity` |
| 26.6 | `export p::*` also exports candidates of a wildcard import that the package never referenced: through `xw_pkgwild` it gives `xw_base::b` (2) and through `xw_list` it gives `xw_other::c` (3), where the names have to be looked up in the compilation unit (500, 700). | `ch26/test_package_export_wildcard_forms` |
| 26.5, 26.3 | In a module with `import so_e::*;` followed by `import so_i::c;`, an unqualified `c` gives the wildcard candidate `so_e::c` (4); the explicit import has to take precedence (7). | `ch26/test_package_search_order_cases` |
| 26.3 | A reference to `z` before the local declaration of `z` binds to that later declaration (30) instead of the compilation-unit `z` (300), and the reference to `k` before the wildcard import binds to `lp::k` (5). | `ch26/test_package_lookup_reference_point` |
| 29.5 | A level-sensitive sequential UDP whose rows `1 1 : 0 : 1` and `1 1 : 1 : 0` select the next state by the current state gives 0 instead of 1 when s rises to make the inputs 1 1 from state 0 (it does not use the current state field there). | `ch29/test_udp_level_sequential_next_state_by_current` |
| 29.8 | Ignores the delays of UDP instances (`u_and2 #3`, `u_buf #(2, 4)`): the outputs change at once (listed above for sequential UDPs; here for combinational ones too). | `ch29/test_udp_instance_delay_name_and_terminal_forms` |
| 36.10.1, 38.36.2 | A cbAfterDelay registration with time type vpiSuppressTime is accepted: vpi_chk_error returns 0 and no cbPLIError callback occurs, although 38.36.2 makes it an error. | `ch36/test_vpi_chk_error_pli_error_callback` |
| 38.36.2 | A cbNextSimTime callback gets the time fields of its request (2) in cb_data->time instead of the current simulation time (30) | `ch38/test_vpi_time_callbacks_without_events` |
| 38.21, 38.36.2 | vpi_handle_by_name returns NULL for the instance of an empty module (u_sub), and vpi_register_cb ignores vpiScaledRealTime (it reads high/low as the delay) | `ch38/test_vpi_time_callback_scaled_real` |
| 38.4, 20.2 | vpi_control(vpiFinish, 0) prints '- :0: Verilog $finish' (empty file name, so the runner does not strip it as a banner) while the routine is still running, although $finish(0) prints nothing. | `ch38/test_vpi_control_finish_on_return` |
| 38.11 | vpi_get_str(vpiName) returns a pointer to a string that stays unchanged after a later vpi_get_str call for another object, not one temporary buffer used by every call. | `ch38/test_vpi_string_buffers` |
| 38.34 | vpi_put_value ignores the delay of every delay mode and sets the value at once (the last put wins) | `ch38/test_vpi_put_value_delay_modes_queue` |
| 38.34 | vpi_put_value on a net driven by a continuous assignment has no visible effect (the nets keep the driver value 10) | `ch38/test_vpi_put_value_net_deposit` |
| 38.34 | vpi_put_value on a named event does not trigger it. | `ch38/test_vpi_put_value_event_vector_scaled` |

### Verilator 5.052: illegal designs that it accepts

| Clause | What it does | Tests |
| --- | --- | --- |
| 6.5 | Accepts a procedural write to a module variable on the line before its declaration. | `ch6/test_illegal_variable_used_before_declaration` |
| 6.5, 23.3.3 | Accepts a variable connected to an inout port of an instance. | `ch6/test_illegal_variable_actual_on_inout_port` |
| 6.5, 23.2.2.3 | Accepts `inout var logic p`. | `ch6/test_illegal_inout_port_declared_as_variable` |
| 6.5, 11.5.3 | Accepts `assign v[0] = ...` together with `initial v[i] = ...` (i a variable). | `ch6/test_illegal_variable_index_prefix_mixed_writers` |
| 6.6.2 | Accepts two continuous assignments sharing bit 1 of a uwire vector. | `ch6/test_illegal_uwire_overlapping_bit_drivers` |
| 6.12, 11.3.1 | Accepts `r & 1` and `r << 1` with a real `r` (warnings only). | `ch6/test_illegal_real_operand_bitwise_and`, `ch6/test_illegal_real_operand_shift` |
| 6.19 | Accepts an enum name value that uses a hierarchical name (`A = u.BASE`, a localparam of an instance) and gives A the value 4; hierarchical names are not allowed in enum values. | `ch6/test_illegal_enum_value_hierarchical_name` |
| 6.19 | Accepts `enum logic signed [3:0] {LO = -7, HI = 8}` and truncates HI to -8; 8 is out of range for a signed 4-bit base (the discarded bits 0 differ from the sign bit 1), which is an error. | `ch6/test_illegal_enum_signed_value_out_of_range` |
| 6.21 | Accepts `initial count = 5;` on a line before the declaration `int count;`; a variable declaration shall precede any simple reference to it. | `ch6/test_illegal_variable_referenced_before_declaration` |
| 6.21 | Accepts a static variable declared with an initializer but without the keyword static in a static task and in an initial block. | `ch6/test_illegal_static_task_variable_initializer_no_keyword`, `ch6/test_illegal_initial_block_variable_initializer_no_keyword` |
| 6.21 | Accepts `assign w = h.value;`, which reads a member of a class object outside a procedural block. | `ch6/test_illegal_continuous_assign_reads_class_member` |
| 6.21 | Accepts `force av = 1;` on a variable of an automatic task. | `ch6/test_illegal_force_automatic_variable` |
| 7.12.3, 11.4.8 | Accepts `a.and with (real'(item))` on an int array, although the bitwise AND of and() is not defined for the real type of the with expression. | `ch7/test_illegal_reduction_and_with_real_expression` |
| 8.19 | Accepts a second assignment to an instance constant (`const int k;`) in the constructor. | `ch8/test_illegal_instance_constant_assigned_twice` |
| 8.19 | Accepts `const static int limit;` (an instance constant declared static) assigned in the constructor. | `ch8/test_illegal_const_static_instance_constant` |
| 11.5.1 | Accepts `v[0:3]` for `logic [7:0] v` and runs the design. The first expression of a non-indexed part-select shall address a more significant bit than the second, so the design is illegal. | `ch11/test_illegal_part_select_reversed_bounds` |
| 19.5.2 | Accepts `bins others[] = default sequence;`. | `ch19/test_illegal_cg_default_sequence_array` |
| 19.8.1 | Accepts `option.weight = w;` where `w` is a formal argument of the overridden sample method. | `ch19/test_illegal_cg_sample_arg_in_option` |
| 28.3.5 | Accepts a gate instance array name declared twice with two ranges (`t_nand[0:1] (https://github.com/kurochan001/kirimasim-tests/blob/b13204c/docs/...), t_nand[2:3] (https://github.com/kurochan001/kirimasim-tests/blob/b13204c/docs/...)`) without an error; one instance name may have only one range. | `ch28/test_illegal_gate_array_split_range` |
| 26.3 | Accepts a module that imports a package declared later in the same source file; the package has to be compiled before the importing scope. | `ch26/test_illegal_package_imported_before_compiled` |
| 26.3 | Accepts explicit imports of `width` from two different packages in one scope. | `ch26/test_illegal_package_explicit_import_two_packages` |
| 26.3 | Accepts an explicit import of `width` into a scope that declares `width` itself. | `ch26/test_illegal_package_explicit_import_local_name` |
| 24.3, 3.14.2.2 | Accepts a later timeunit in a program that does not match the first one, and a timeprecision among the program items that repeats nothing. | `ch24/test_illegal_program_timeunit_mismatch`, `ch24/test_illegal_program_timeprecision_after_item` |
| 29.3.6 | Accepts `-` in the table of a combinational UDP, which 29.3.6 allows only in the output field of a sequential UDP. (Icarus Verilog 13.0 stops on an internal assertion.) | `ch29/test_illegal_udp_hyphen_combinational` |
| 29.7 | Accepts a begin-end block with two assignments as the initial statement of a UDP. | `ch29/test_illegal_udp_initial_block` |
| 35.5.4 | Accepts an import declaration with a ref formal (only the link step fails for the missing C function). | `ch35/test_illegal_dpi_import_ref_formal` |
| 35.5.4 (footnote 25) | Accepts `import "DPI-C" function :initial int c_f();` in a module. | `ch35/test_illegal_dpi_import_override_specifier` |
| 35.5.2 | Accepts a pure imported function with an output argument. | `ch35/test_illegal_dpi_pure_function_output` |

### Both releases: results

| Clause | What it does | Tests |
| --- | --- | --- |
| 26.3 | A reference to `y` written before `import lv::y;` gives `lv::y` (7) instead of the compilation-unit `y` (400): an explicit import makes the name locally visible only after it. Verilator also binds `w_first` to the later local `w` (30 instead of 300). | `ch26/test_package_local_visibility` |

### Both releases: illegal designs that it accepts

| Clause | What it does | Tests |
| --- | --- | --- |
| 6.12, 11.3.1 | Accept `r % 2.0` with a real `r` (Verilator with warnings only). | `ch6/test_illegal_real_operand_modulus` |
| 6.20.5 | Both accept a reference to a module-body specparam (`$display("%0d", tHold)` in an initial block) on a line before its declaration and print 5; a specparam declared outside a specify block shall be declared before it is referenced. | `ch6/test_illegal_specparam_used_before_declaration` |
| 6.21 | Both accept `assign w = da[0];`, a continuous assignment that reads an element of a dynamic array; such references are limited to procedural blocks. | `ch6/test_illegal_continuous_assign_reads_dynamic_element` |
| 27.4, 27.6 | Both accept `genblk1[1].x`, a hierarchical reference from the module into an unnamed loop generate block; such declarations can be referenced only from within the hierarchy of that block, and genblk<n> is a name for external interfaces only. | `ch27/test_illegal_generate_unnamed_loop_block_reference` |
| 29.3.4 | Accept a combinational UDP entry `x x : 1;` whose inputs are all x and whose output is not x (29.3.4 requires x). | `ch29/test_illegal_udp_all_x_entry_not_x` |
| 29.3.6 | Accept a value change (01) in the current state field of a sequential UDP entry; Table 29-1 permits (vw) only in input fields. | `ch29/test_illegal_udp_value_change_in_state_field` |
| 29.7, 29.3 | Accept `initial q = 2;` in a UDP; init_val allows only 1'b0, 1'b1, 1'bx (and the uppercase forms), 1 and 0. | `ch29/test_illegal_udp_initial_value_two` |
| 30.4.1 | Accept a module path whose source is an input port declared `input var logic a` (a variable); 30.4.1 requires the source to be a net. | `ch30/test_illegal_specify_path_source_variable_port` |
| 33.4.1.1 | Both accept a config whose design statement names another config. (Icarus skips config declarations.) | `ch33/test_illegal_config_design_is_config` |
