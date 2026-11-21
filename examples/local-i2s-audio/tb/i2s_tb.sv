`timescale 1ns/1ps
// Vector-driven bench. Every row gives the inputs of one clock and the outputs expected before
// its edge; the expected values come from the model in run.py. The receiver listens either to
// the transmitter or to pins driven from the row, chosen by sel_ext.
module i2s_tb;
    parameter WORD = 16, SLOT = 16, MUTATION = 0;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 1, in_valid = 0, sel_ext = 0, ext_sck = 0, ext_ws = 0, ext_sd = 0;
    reg [WORD-1:0] in_left = 0, in_right = 0;
    wire in_ready, sck, ws, sd, underrun;
    wire [WORD-1:0] rx_left, rx_right;
    wire [7:0] rx_frames, rx_errors;

    i2s_tx #(.WORD(WORD), .SLOT(SLOT), .MUTATION(MUTATION)) tx (.*);
    wire m_sck = sel_ext ? ext_sck : sck;
    wire m_ws = sel_ext ? ext_ws : ws;
    wire m_sd = sel_ext ? ext_sd : sd;
    i2s_rx #(.WORD(WORD), .SLOT(SLOT), .MUTATION(MUTATION)) rx (
        .sck(m_sck), .rst_n(rst_n), .ws(m_ws), .sd(m_sd),
        .left(rx_left), .right(rx_right), .frames(rx_frames), .errors(rx_errors));

    integer fd, n, v[0:16], checks = 0, accepted = 0, delivered = 0, errors = 0;
    integer running = 0, since_edge = 0, slot_len = 0, closed_len = 0;
    reg [7:0] seen_frames = 0, seen_errors = 0;
    bit was_running = 0, prev_ext_sck = 0, edge_seen = 0, edge_ws = 0, armed = 0;
    bit stretched = 0, right_first = 0, closed = 0;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d", checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, i2s_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        #1 rst_n = 0;                        // a falling edge, so that the asynchronous reset is taken
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4],
                        v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14], v[15], v[16]);
            if (n != 17) $fatal(1, "bad row");
            if (!v[0] && was_running && running > 4 * SLOT && running % (4 * SLOT) != 0) $display("COVER reset/midframe");
            rst_n = v[0];
            in_valid = v[1];
            in_left = v[2];
            in_right = v[3];
            sel_ext = v[4];
            ext_ws = v[6];
            ext_sd = v[7];
            #1;
            ext_sck = v[5];                      // the clock moves after the data it will sample
            closed = 0;
            if (!rst_n) begin
                edge_seen = 0;
                armed = 0;
                slot_len = 0;
                since_edge = 0;
                stretched = 0;
                right_first = 0;
            end else if (sel_ext) begin
                since_edge = since_edge + 1;
                if (ext_sck && !prev_ext_sck) begin
                    if (edge_seen && since_edge >= 4) stretched = 1;
                    since_edge = 0;
                    if (edge_seen && ext_ws != edge_ws) begin
                        if (armed) begin
                            closed = 1;
                            closed_len = slot_len + 1;
                        end else if (ext_ws) right_first = 1;
                        armed = 1;
                        slot_len = 0;
                    end else if (armed) slot_len = slot_len + 1;
                    edge_seen = 1;
                    edge_ws = ext_ws;
                end
            end
            prev_ext_sck = ext_sck;
            #1;
            if (in_ready !== v[8][0] || underrun !== v[12][0]) fail("I2S_TX_FLOW");
            if (sck !== v[9][0]) fail("I2S_TX_SCK");
            if (ws !== v[10][0]) fail("I2S_TX_WS");
            if (sd !== v[11][0]) fail("I2S_TX_SD");
            if (rx_frames !== v[13][7:0]) fail("I2S_RX_VALID");
            if (rx_left !== v[14][WORD-1:0] || rx_right !== v[15][WORD-1:0]) fail("I2S_RX_DATA");
            if (rx_errors !== v[16][7:0]) fail("I2S_RX_ERROR");
            if (!rst_n) begin
                seen_frames = 0;
                seen_errors = 0;
            end else begin
                if (in_valid && in_ready) begin
                    accepted = accepted + 1;
                    $display("COVER flow/accept");
                end
                if (in_valid && !in_ready) $display("COVER flow/wait");
                if (!in_valid && in_ready) $display("COVER flow/idle-ready");
                if (underrun) $display("COVER flow/underrun");
                if (closed) begin
                    if (closed_len == SLOT && rx_errors == seen_errors) $display("COVER ext/exact-slot");
                    if (closed_len < WORD) $display("COVER rx/pad-short");
                    if (closed_len > WORD) $display("COVER rx/extra-bits");
                end
                if (rx_errors != seen_errors) begin
                    errors = errors + 1;
                    if (closed && closed_len < SLOT) $display("COVER error/short-slot");
                    if (closed && closed_len > SLOT) $display("COVER error/long-slot");
                end
                if (rx_frames != seen_frames) begin
                    delivered = delivered + 1;
                    if (sel_ext) begin
                        $display("COVER ext/frame");
                        if (stretched) $display("COVER ext/stretched-clock");
                        if (right_first) $display("COVER ext/start-on-right");
                        right_first = 0;
                    end else begin
                        $display("COVER loop/frame");
                        if (rx_left[WORD-1] && !rx_right[WORD-1]) $display("COVER loop/msb-left");
                        if (!rx_left[WORD-1] && rx_right[WORD-1]) $display("COVER loop/msb-right");
                        if (rx_left != rx_right) $display("COVER loop/channels-differ");
                    end
                end
                seen_frames = rx_frames;
                seen_errors = rx_errors;
            end
            was_running = rst_n;
            running = rst_n ? running + 1 : 0;
            @(posedge clk);
            checks = checks + 1;
            @(negedge clk);
        end
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT delivered=%0d", delivered);
        $display("COUNT errors=%0d", errors);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
