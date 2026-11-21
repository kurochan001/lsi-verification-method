`timescale 1ns/1ps
// What each SystemVerilog type looks like on the C side, and back.
module dpi_probe_tb;
    import "DPI-C" pure function byte probe_byte(input byte value);
    import "DPI-C" pure function shortint unsigned probe_shortint(input shortint unsigned value);
    import "DPI-C" pure function int probe_int(input int value);
    import "DPI-C" pure function longint probe_longint(input longint value);
    import "DPI-C" pure function real probe_real(input real value);
    import "DPI-C" function void probe_bit(input bit [7:0] narrow, input bit [39:0] wide,
                                           output bit [39:0] result);
    import "DPI-C" function int probe_logic(input logic [7:0] value, output logic [7:0] result);
    import "DPI-C" function int probe_string(input string text);
    import "DPI-C" function chandle probe_handle_new(input int value);
    import "DPI-C" function int probe_handle_take(input chandle handle);
    import "DPI-C" function int probe_open(input byte unsigned bytes []);
    import "DPI-C" context function int probe_context(input int value);
    import "DPI-C" context task probe_import_task(input int value);
    export "DPI-C" function probe_note;
    export "DPI-C" task probe_task;

    int notes;
    bit [39:0] wide;
    logic [7:0] four, answer;
    chandle handle;
    int count;
    byte unsigned four_bytes [4] = '{8'd1, 8'd2, 8'd3, 8'd4};
    byte unsigned ranged [7:2] = '{8'd10, 8'd20, 8'd30, 8'd40, 8'd50, 8'd60};

    function void probe_note(input int value);
        notes += value;
    endfunction

    // No delay inside: Verilator 5.052 rejects timing controls in an exported task.
    task probe_task(input int value);
        notes += 100 * value;
    endtask

    initial begin
        notes = 0;
        $display("PROBE byte=%0d", probe_byte(-128));
        $display("PROBE shortint=%0d", probe_shortint(16'hffff));
        $display("PROBE int=%0d", probe_int(-2147483647));
        $display("PROBE longint=%0d", probe_longint(64'sd3000000000));
        $display("PROBE real=%0.3f", probe_real(1.5));
        probe_bit(8'ha5, 40'h12_3456_789a, wide);
        $display("PROBE bit=%h", wide);
        four = 8'bxxzz_1010;
        count = probe_logic(four, answer);
        $display("PROBE logic_in_unknown=%0d", count);
        $display("PROBE logic_out=%b", answer);
        $display("PROBE string=%0d", probe_string("checksum"));
        handle = probe_handle_new(1234);
        $display("PROBE handle=%0d", probe_handle_take(handle));
        $display("PROBE open4=%0d", probe_open(four_bytes));
        $display("PROBE open6=%0d", probe_open(ranged));
        count = probe_context(5);
        $display("PROBE context_scope_length=%0d", count);
        $display("PROBE export_function=%0d", notes);
        probe_import_task(7);
        $display("PROBE export_task=%0d", notes);
        $display("RESULT PASS checks=15");
        $finish;
    end
endmodule
