`timescale 1ns/1ps
module clock_switch_tb;
    parameter BOOT=1, MUTATION=0;
    reg clk=0, rst_n=1, sel=0, idle=1;
    reg [2:0] div=0;
    reg qa=0;
    reg [1:0] qb=0;
    wire clk_a = qa;             // 周期8ns: 正相1グリッド
    wire clk_b = (qb == 2'd0);   // 周期12ns: 正相1グリッド
    wire engine_clk, switching, sel_q;
    wire [3:0] ratio, div_pend, phase;
    wire [1:0] idle_run;
    wire busy_hold;
    clock_switch #(.BOOT(BOOT), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .clk_a(clk_a), .clk_b(clk_b), .sel(sel),
        .div(div), .idle(idle), .engine_clk(engine_clk), .switching(switching),
        .sel_q(sel_q), .ratio(ratio), .div_pend(div_pend), .phase(phase),
        .idle_run(idle_run), .busy_hold(busy_hold));
    always #2 clk = ~clk;                       // 主クロック4ns
    always @(posedge clk) begin qa <= ~qa; qb <= (qb == 2'd2) ? 2'd0 : qb + 2'd1; end
    integer fd, n, checks=0, ecount=0;
    reg engine_prev=0;
    reg eng_n=0, sw_n=0, selq_n=0, sw_col_n=0, saw_reset=0;
    reg [3:0] ratio_n=0;
    reg sel_n=0;
    reg [63:0] v[0:12];
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d sel=%b div=%0d idle=%b | rtl eng=%b sw=%b bh=%b ratio=%b irun=%b ecnt=%0d dpend=%b phase=%b selq=%b | exp eng=%b sw=%b bh=%b ratio=%b irun=%b ecnt=%h dpend=%b phase=%b selq=%b", checks, sel, div, idle, engine_clk, switching, busy_hold, ratio, idle_run, ecount, div_pend, phase, sel_q, v[4][0], v[5][0], v[6][0], v[7][3:0], v[8][1:0], v[9][31:0], v[10][3:0], v[11][3:0], v[12][0]); end
    endtask
    always @(posedge clk) begin
        if (rst_n) begin
            if (engine_clk && !engine_prev) ecount = ecount + 1;
        end
        engine_prev = engine_clk;
    end
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, clock_switch_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12]);
            if (n != 13) $fatal(1, "bad row");
            rst_n = v[0][0]; sel = v[1][0]; div = v[2][2:0]; idle = v[3][0];
            if (!rst_n) begin ecount = 0; engine_prev = 0; qa = 0; qb = 0; eng_n = 0; sw_n = 0; selq_n = 0; end
            #1;
            // グリッチ検査は列比較より前: 凍結ウィンドウの翌行にも出力が残らないこと、
            // 系統が入れ替わった行で出力がHighのままではないことを確かめる。
            if (engine_clk && sw_n) fail("CLK_GLITCH");
            if (engine_clk && sel_q !== selq_n) fail("CLK_GLITCH");
            if (ratio !== v[7][3:0]) fail("CLK_DIV");
            if (phase !== v[11][3:0]) fail("CLK_DIV");
            if (idle_run !== v[8][1:0]) fail("CLK_DIV");
            if (div_pend !== v[10][3:0]) fail("CLK_DIV");
            if (engine_clk !== v[4][0]) fail("CLK_SEL");
            if (switching !== v[5][0]) fail("CLK_SEL");
            if (busy_hold !== v[6][0]) fail("CLK_SEL");
            if (ecount[31:0] !== v[9][31:0]) fail("CLK_SEL");
            if (sel_q !== v[12][0]) fail("CLK_SEL");
            if (switching) begin
                $display("COVER glitch/quiet-window");
                if (sw_col_n) $display("COVER glitch/no-edge-in-window");
            end
            if (switching && !sw_col_n) begin
                if (sel) $display("COVER switch/a-to-b");
                else $display("COVER switch/b-to-a");
            end
            if (!switching && sw_col_n) $display("COVER engine/resume-after-switch");
            if (busy_hold) $display("COVER engine/hold-while-busy");
            if (ratio !== ratio_n) begin
                if (ratio > ratio_n) $display("COVER div/increase");
                else $display("COVER div/decrease");
                $display("COVER div/effective-when-idle");
            end
            if (ratio === 4'd8) $display("COVER div/ratio-8");
            if (!rst_n) begin
                saw_reset = 1;
            end else if (saw_reset && idle) begin
                $display("COVER reset/recovery"); saw_reset = 0;
            end
            sw_col_n = switching; ratio_n = ratio; eng_n = engine_clk; sw_n = switching; selq_n = sel_q; sel_n = sel;
            checks = checks + 1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
