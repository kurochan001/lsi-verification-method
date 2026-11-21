// Self-composition: two copies share every public input (reset, start, cancel, out_ready) and get
// independent keys and blocks. The public outputs must be equal on every clock, for every input.
// The zeroization invariants are asserted inside aes128_core under `ifdef FORMAL`.
module aes_ct_formal #(parameter MUTATION = 0) (
    input wire clk, rst_n, start, cancel, out_ready,
    input wire [127:0] key0, key1, block0, block1
);
    wire ready0, ready1, busy0, busy1, valid0, valid1;
    wire [3:0] progress0, progress1;
    wire [127:0] out0, out1;
    aes128_core #(.MUTATION(MUTATION)) a(
        .clk(clk), .rst_n(rst_n), .start(start), .cancel(cancel), .key(key0), .block(block0),
        .out_ready(out_ready), .ready(ready0), .busy(busy0), .out_valid(valid0), .progress(progress0),
        .out_block(out0));
    aes128_core #(.MUTATION(MUTATION)) b(
        .clk(clk), .rst_n(rst_n), .start(start), .cancel(cancel), .key(key1), .block(block1),
        .out_ready(out_ready), .ready(ready1), .busy(busy1), .out_valid(valid1), .progress(progress1),
        .out_block(out1));
    reg past = 1'b0;
    reg handshake = 1'b0;
    always @(posedge clk) begin
        past <= 1'b1;
        handshake <= rst_n && !cancel && valid0 && out_ready;
        if (!past) as_initial_reset: assume(!rst_n);
        if (past) begin
            ap_timing: assert({ready0, busy0, valid0, progress0} == {ready1, busy1, valid1, progress1});
            cp_done: cover(valid0);
            cp_cancel_busy: cover(rst_n && cancel && busy0);
            cp_hold: cover(rst_n && valid0 && !out_ready && $past(valid0));
            cp_back_to_back: cover(rst_n && !cancel && start && ready0 && handshake);
        end
    end
endmodule
