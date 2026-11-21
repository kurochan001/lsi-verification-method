`timescale 1ns/1ps
// One row of the vector file per clock (kind 0), or one bound for the rotation angle left
// after a pipeline stage (kind 1). Each output is judged twice: against a tolerance around
// the mathematical result, and bit for bit against the integer model.
module cordic_tb;
    parameter WIDTH = 16, ITER = 16, GUARD = 4, MUTATION = 0;
    localparam ZW = 16 + GUARD;
    localparam DUMP_ROWS = 4096;   // the waveform keeps the first rows of a long sweep

    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n = 0, in_valid = 0, mode = 0;
    reg signed [WIDTH-1:0] x_in = 0, y_in = 0;
    reg [15:0] z_in = 0;
    wire out_valid;
    wire signed [WIDTH:0] x_out, y_out;
    wire [15:0] z_out;

    cordic #(.WIDTH(WIDTH), .ITER(ITER), .GUARD(GUARD), .MUTATION(MUTATION)) dut (.*);

    // Copies of the angle held by every stage, for the residual check.
    wire signed [ZW-1:0] stage_z [0:ITER];
    wire                 stage_rotation [0:ITER];
    genvar g;
    generate
        for (g = 0; g <= ITER; g = g + 1) begin : g_probe
            assign stage_z[g] = dut.z[g];
            assign stage_rotation[g] = dut.valid[g] && !dut.m[g];
        end
    endgenerate

    integer fd, n, v [0:16], rows = 0, stage;
    integer accepted = 0, completed = 0, rotations = 0, vectorings = 0, inexact = 0;
    integer bound [0:ITER];
    integer ex, ey, rx, ry, dz, got_x, got_y, last_mode = -1, in_flight = 0, previous_valid = 0;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d", rows);
        end
    endtask

    // Report a goal once per run; a sweep would otherwise print it for every operation.
    reg reported [0:79];
    task reach(input integer id, input string goal);
        begin
            if (reported[id] !== 1'b1) begin
                reported[id] = 1'b1;
                $display("COVER %s", goal);
            end
        end
    endtask

    function integer magnitude(input integer value);
        magnitude = value < 0 ? -value : value;
    endfunction

    // Distance between two 16-bit angles on the circle.
    function integer turn_distance(input integer a, input integer b);
        integer d;
        begin
            d = (a - b) & 16'hffff;
            turn_distance = d > 32768 ? 65536 - d : d;
        end
    endfunction

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, cordic_tb);
        for (stage = 0; stage <= ITER; stage = stage + 1) bound[stage] = -1;
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10],
                        v[11], v[12], v[13], v[14], v[15], v[16]);
            if (n != 17) $fatal(1, "bad row");
            if (v[0] == 1) begin
                if (v[1] > ITER) $fatal(1, "bad stage");
                bound[v[1]] = v[2];
                rows = rows + 1;
            end else begin
                if (!v[1] && rst_n && in_flight != 0) reach(0, "reset/pending");
                rst_n = v[1];
                in_valid = v[2];
                mode = v[3];
                x_in = v[4][WIDTH-1:0];
                y_in = v[5][WIDTH-1:0];
                z_in = v[6][15:0];
                #1;
                if (out_valid !== v[7][0]) fail("CORDIC_VALID");
                if (out_valid) begin
                    if (^{x_out, y_out, z_out} === 1'bx) fail("CORDIC_UNKNOWN");
                    got_x = x_out;
                    got_y = y_out;
                    ex = $signed(v[8][19:0]);
                    ey = $signed(v[9][19:0]);
                    rx = $signed(v[11][19:0]);
                    ry = $signed(v[12][19:0]);
                    dz = turn_distance(z_out, v[13]);
                    if (magnitude(got_x - rx) > v[14] || magnitude(got_y - ry) > v[15] || dz > v[16])
                        fail("CORDIC_TOLERANCE");
                    if (got_x !== ex || got_y !== ey || z_out !== v[10][15:0]) fail("CORDIC_DATA");
                    completed = completed + 1;
                    if (ex != rx || ey != ry || v[10] != v[13]) begin
                        inexact = inexact + 1;
                        reach(4, "error/inexact");
                    end
                    if (magnitude(got_x - rx) == v[14] || magnitude(got_y - ry) == v[15])
                        reach(8, "error/at-limit");
                end
                for (stage = 0; stage <= ITER; stage = stage + 1)
                    if (rst_n && stage_rotation[stage] === 1'b1 && bound[stage] >= 0 &&
                        (stage_z[stage] > bound[stage] || stage_z[stage] < -bound[stage]))
                        fail("CORDIC_RESIDUAL");
                if (!rst_n) begin
                    in_flight = 0;
                    last_mode = -1;
                    previous_valid = 0;
                end else begin
                    if (out_valid) in_flight = in_flight - 1;
                    if (in_valid) begin
                        accepted = accepted + 1;
                        in_flight = in_flight + 1;
                        if (mode) vectorings = vectorings + 1;
                        else rotations = rotations + 1;
                        if (previous_valid) reach(12, "valid/back-to-back");
                        if (last_mode >= 0 && last_mode != mode) reach(16, "mode/interleaved");
                        last_mode = mode;
                        if (!mode) begin
                            reach(20 + z_in[15:14], $sformatf("rotate/quadrant%0d", z_in[15:14]));
                            if (z_in[15] ^ z_in[14]) reach(24, "fold/rotation");
                            if (z_in == 16'h0000) reach(28, "rotate/angle-zero");
                            if (z_in == 16'h3fff || z_in == 16'hbfff) reach(32, "fold/just-inside");
                            if (z_in == 16'h4000 || z_in == 16'hc000) reach(36, "fold/boundary");
                            if (z_in == 16'h8000) reach(40, "rotate/half-turn");
                            if (x_in == {1'b1, {(WIDTH-1){1'b0}}} || y_in == {1'b1, {(WIDTH-1){1'b0}}})
                                reach(44, "operand/most-negative");
                            if (x_in == {1'b0, {(WIDTH-1){1'b1}}} && y_in == {1'b0, {(WIDTH-1){1'b1}}})
                                reach(48, "operand/longest");
                        end else begin
                            if (x_in == 0 && y_in == 0) reach(52, "vector/zero");
                            else if (y_in == 0) reach(56 + (x_in < 0 ? 1 : 0), x_in < 0 ? "vector/x-axis-negative" : "vector/x-axis-positive");
                            else if (x_in == 0) reach(60, "vector/y-axis");
                            else reach(64 + {y_in < 0, (x_in < 0) ^ (y_in < 0)}, $sformatf("vector/quadrant%0d", {y_in < 0, (x_in < 0) ^ (y_in < 0)}));
                            if (x_in < 0) reach(68, "fold/vectoring");
                            if (x_in != 0 && y_in != 0 && magnitude(x_in) + magnitude(y_in) <= 3)
                                reach(72, "vector/short");
                        end
                    end else if (in_flight != 0) reach(76, "valid/gap");
                    previous_valid = in_valid;
                end
                @(posedge clk);
                #1;
                rows = rows + 1;
                if (rows == DUMP_ROWS) $dumpoff;
                @(negedge clk);
            end
        end
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT completed=%0d", completed);
        $display("COUNT rotations=%0d", rotations);
        $display("COUNT vectorings=%0d", vectorings);
        $display("COUNT inexact=%0d", inexact);
        $display("RESULT PASS checks=%0d", rows);
        $finish;
    end
endmodule
