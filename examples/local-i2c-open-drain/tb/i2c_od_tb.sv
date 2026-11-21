`timescale 1ns/1ps
// Replays the SDA line, digitised from the ngspice waveform, at its own times and checks
// the reading side against the expected SCL edges, sampling points and byte. The expected
// values come from the Python model; the phase and unknown-value monitors do not use it.
module i2c_od_tb #(parameter DIV = 125, SAMPLE = 62, MUTATION = 0);
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg start = 1'b0;
    reg sda_in = 1'b1;
    wire scl, busy, done, smp;
    wire [7:0] data;

    i2c_rx_master #(.DIV(DIV), .SAMPLE(SAMPLE), .MUTATION(MUTATION)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .sda_in(sda_in),
        .scl(scl), .busy(busy), .done(done), .smp(smp), .data(data));

    always #5 clk = ~clk;          // rising edges at 5, 15, 25 ... ns

    string events, expectations, wave;
    integer efd, xfd, checks, n_edges, n_samples, edge_i, sample_i, bit_value, scanned;
    integer event_value, edge_value;
    real event_time, edge_time, sample_time, done_time, end_time;
    real edge_t [0:63];
    integer edge_v [0:63];
    real samp_t [0:15];
    integer samp_b [0:15];
    reg [7:0] exp_data;
    reg finished = 1'b0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "%s at %0.3f ns", label, $realtime);
        end
    endtask

    function automatic bit near(input real a, input real b);
        near = (a - b) < 0.0005 && (b - a) < 0.0005;
    endfunction

    initial begin
        if (!$value$plusargs("EVENTS=%s", events) || !$value$plusargs("EXPECT=%s", expectations) ||
            !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing run arguments");
        $dumpfile(wave);
        $dumpvars(0, i2c_od_tb);
        efd = $fopen(events, "r");
        xfd = $fopen(expectations, "r");
        if (!efd || !xfd) $fatal(1, "cannot open run files");
        scanned = $fscanf(xfd, "EDGES %d\n", n_edges);
        if (scanned != 1 || n_edges < 1 || n_edges > 64) $fatal(1, "bad expected edge count");
        for (edge_i = 0; edge_i < n_edges; edge_i = edge_i + 1) begin
            if ($fscanf(xfd, "%f %d\n", edge_time, edge_value) != 2) $fatal(1, "bad expected edge");
            edge_t[edge_i] = edge_time; edge_v[edge_i] = edge_value;
        end
        scanned = $fscanf(xfd, "SAMPLES %d\n", n_samples);
        if (scanned != 1 || n_samples < 1 || n_samples > 16) $fatal(1, "bad expected sample count");
        for (sample_i = 0; sample_i < n_samples; sample_i = sample_i + 1) begin
            if ($fscanf(xfd, "%f %d\n", sample_time, bit_value) != 2) $fatal(1, "bad expected sample");
            samp_t[sample_i] = sample_time; samp_b[sample_i] = bit_value;
        end
        if ($fscanf(xfd, "DONE %f %h\n", done_time, exp_data) != 2) $fatal(1, "bad expected done line");
        if ($fscanf(xfd, "END %f\n", end_time) != 1) $fatal(1, "bad expected end line");
        edge_i = 0; sample_i = 0; checks = 0;
        fork
            begin : reset_and_start
                #20 rst_n = 1'b1;
                #2 start = 1'b1;          // taken by the rising edge at 25 ns
                #4 start = 1'b0;
            end
            begin : line_events
                while ($fscanf(efd, "%f %d\n", event_time, event_value) == 2) begin
                    if (event_time <= $realtime) $fatal(1, "line events are not in time order");
                    #(event_time - $realtime) sda_in = event_value[0];
                end
                if (!$feof(efd)) $fatal(1, "unreadable line event");
            end
            begin : watchdog
                #(end_time);
                if (!finished) fail("I2C_TIMEOUT");
            end
        join_none
    end

    // Every SCL change after reset must be the next expected edge, at its time.
    always @(scl) if (rst_n && !finished) begin
        if (scl === 1'bx) fail("I2C_UNKNOWN");
        if (edge_i >= n_edges || !near($realtime, edge_t[edge_i]) || scl !== edge_v[edge_i][0]) begin
            $display("SCL %b at %0.3f ns, edge %0d expected %0d at %0.3f ns", scl, $realtime, edge_i,
                     edge_i < n_edges ? edge_v[edge_i] : -1, edge_i < n_edges ? edge_t[edge_i] : -1.0);
            fail("I2C_SCL");
        end
        edge_i = edge_i + 1;
        checks = checks + 1;
    end

    always @(posedge clk) if (rst_n && !finished) begin
        #1;
        if (^{smp, done, busy} === 1'bx) fail("I2C_UNKNOWN");
        if (smp) begin
            if (!scl) fail("I2C_PHASE");                       // model-free: SDA is read while SCL is high
            if (busy !== 1'b1) fail("I2C_BUSY");               // model-free: busy for the whole byte
            if (sample_i >= n_samples || !near($realtime - 1.0, samp_t[sample_i])) begin
                $display("sample %0d at %0.3f ns", sample_i, $realtime - 1.0);
                fail("I2C_SAMPLE");
            end
            if (data[0] !== samp_b[sample_i][0]) begin
                $display("sample %0d read %b expected %0d", sample_i, data[0], samp_b[sample_i]);
                fail("I2C_BIT");
            end
            sample_i = sample_i + 1;
            checks = checks + 1;
        end
        if (done) begin
            if (sample_i != n_samples) fail("I2C_COUNT");
            if (edge_i != n_edges) fail("I2C_SCL");
            if (!near($realtime - 1.0, done_time)) fail("I2C_DONE");
            if (^data === 1'bx) fail("I2C_UNKNOWN");
            if (busy !== 1'b0) fail("I2C_BUSY");               // model-free: idle again once the byte is done
            if (data !== exp_data) begin
                $display("data %h expected %h", data, exp_data);
                fail("I2C_DATA");
            end
            checks = checks + 1;
            finished = 1'b1;
            #200;
            $display("RESULT PASS checks=%0d", checks);
            $finish;
        end
    end
endmodule
