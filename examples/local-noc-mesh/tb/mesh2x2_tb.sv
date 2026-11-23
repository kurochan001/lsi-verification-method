`timescale 1ns/1ps
module mesh2x2_tb;
    parameter BUF=1, MUTATION=0;
    reg clk=0, rst_n=1;
    reg [3:0] inject_valid=0, egress_ready=0;
    reg [11:0] inject_flit=0;
    wire [3:0] inject_ready, stall, err_rst, egress_valid;
    wire [47:0] egress_pkt;
    mesh2x2 #(.BUF(BUF), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .inject_valid(inject_valid), .inject_flit(inject_flit),
        .egress_ready(egress_ready), .inject_ready(inject_ready), .stall(stall),
        .err_rst(err_rst), .egress_valid(egress_valid), .egress_pkt(egress_pkt));
    always #5 clk = ~clk;
    integer fd, n, checks=0, idle=0, i, wait_bad=-1, pend_left=0, k;
    reg [63:0] v[0:8];
    reg [3:0] estall;
    // モデル受理済みの期待パケット集合。鍵は(宛先ノード, 出所2b, seq4b)でデータ4ビットを保持。
    // 同じ(出所,宛先)でseqが再使用される深さはパス容量(16未満)なので衝突しない。
    reg [3:0] pend_data [0:3][0:63];
    reg pend_used [0:3][0:63];
    reg [3:0] acc_since=0, held=0;
    reg [47:0] held_pkt;
    reg prev_delivery=0;
    reg reachable, delivered, cov_hold=0, cov_burst=0, cov_noloss=0, cov_hol=0, cov_cyclic=0,
        cov_armed=0, cov_1x=0, cov_1y=0, cov_2h=0, cov_bad=0, cov_queued=0,
        cov_flush=0, cov_rec=0, stall_seen=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "row=%0d iv=%b flit=%h irdy=%b estall=%b dstall=%b ev=%b pkt=%h pend=%0d",
            checks, inject_valid, inject_flit, inject_ready, {v[8][0],v[7][0],v[6][0],v[5][0]},
            stall, egress_valid, egress_pkt, pend_left); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, mesh2x2_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8]);
            if (n != 9) $fatal(1, "bad row");
            rst_n = v[0][0]; inject_valid = v[1][3:0]; inject_flit = v[2][11:0];
            egress_ready = v[4][3:0];
            #1;
            estall = {v[8][0], v[7][0], v[6][0], v[5][0]};
            if (inject_ready !== v[3][3:0] || stall !== estall) fail("MESH_BP");
            if (err_rst !== {4{!rst_n}}) fail("MESH_BP");
            if (!rst_n) begin
                if (pend_left > 0 && !cov_flush) begin $display("COVER reset/flush"); cov_flush = 1; end
                for (i = 0; i < 4; i = i + 1)
                    for (k = 0; k < 64; k = k + 1) pend_used[i][k] = 0;
                pend_left = 0; held=0; acc_since=0; prev_delivery=0; idle=0; wait_bad=-1; stall_seen=0;
            end
            // 配信イベント: 経路→期待集合の突合→データの順。順番を決定的にする。
            for (i=0; i<4; i=i+1)
                if (held[i] && (egress_valid[i] !== 1'b1 || egress_pkt[i*12+:12] !== held_pkt[i*12+:12]))
                    fail("MESH_BP");
            delivered = 0;
            for (i = 0; i < 4; i = i + 1) if (egress_valid[i] && egress_ready[i]) begin
                delivered = 1;
                if (egress_pkt[i*12 + 11 -: 2] !== i[1:0]) fail("MESH_ROUTE");
                k = {egress_pkt[i*12 + 9 -: 2], egress_pkt[i*12 + 7 -: 4]};
                if (pend_used[i][k] !== 1'b1) fail("MESH_BP");
                if (pend_data[i][k] !== egress_pkt[i*12 +: 4]) fail("MESH_DATA");
                pend_used[i][k] = 0;
                pend_left = pend_left - 1;
                if (!cov_queued && pend_left >= 1) begin $display("COVER flow/queued-drain"); cov_queued = 1; end
                if (!cov_1x && i == 1 && k[5:4] == 0) begin $display("COVER route/1hop-x"); cov_1x = 1; end
                if (!cov_1y && i == 2 && k[5:4] == 0) begin $display("COVER route/1hop-y"); cov_1y = 1; end
                if (!cov_2h && i == 3 && k[5:4] == 0) begin $display("COVER route/2hop"); cov_2h = 1; end
                if (held[i]) begin
                    if (!cov_hold) begin $display("COVER bp/hold"); cov_hold = 1; end
                end
                if (!cov_cyclic && $countones(acc_since) >= 2) begin $display("COVER live/cyclic-drain"); cov_cyclic = 1; end
                if (cov_flush && !cov_rec) begin $display("COVER reset/recovery"); cov_rec = 1; cov_flush = 0; end
                acc_since = 0;
            end
            // 注入受理: モデル側ready列とXY到達判定で決まる期待集合を作る。無効宛先は破棄観測へ。
            for (i = 0; i < 4; i = i + 1) if (inject_valid[i]) begin
                reachable = inject_flit[10] >= i[0] && inject_flit[11] >= i[1];
                if (!reachable) begin
                    if (inject_ready[i] && wait_bad < 0) wait_bad = 6;
                end else if (inject_ready[i]) begin
                    k = {inject_flit[9:8], inject_flit[7:4]};
                    if (pend_used[inject_flit[11:10]][k]) $fatal(1,"source reused a pending sequence");
                    pend_data[inject_flit[11:10]][k] = inject_flit[3:0];
                    pend_used[inject_flit[11:10]][k] = 1;
                    pend_left = pend_left + 1;
                    acc_since = acc_since | (4'd1 << i);
                    if (!delivered && !cov_armed) begin $display("COVER live/timeout-armed"); cov_armed = 1; end
                end
            end
            // 被覆とライブネス: stall中の注入ブロック、stall中の配信、出口保持、待機周期。
            if (!cov_hol && (inject_valid & ~inject_ready) != 0 && estall != 0) begin
                $display("COVER hol/block-observed"); cov_hol = 1;
            end
            if (!cov_burst && prev_delivery && delivered) begin $display("COVER bp/burst-2"); cov_burst = 1; end
            held = egress_valid & ~egress_ready; held_pkt=egress_pkt; prev_delivery=delivered;
            if (estall != 0 || egress_ready != 4'hF) stall_seen = 1;
            if (!cov_noloss && stall_seen && estall == 0 && pend_left == 0 &&
                egress_ready == 4'hF && checks > 10) begin
                $display("COVER bp/no-loss"); cov_noloss = 1;
            end
            if (wait_bad > 0) wait_bad = wait_bad - 1;
            else if (wait_bad == 0) begin
                wait_bad = -1;
                if (!cov_bad) begin $display("COVER route/bad-drop"); cov_bad = 1; end
            end
            if (pend_left > 0) begin
                if (egress_ready == 15 && (inject_valid & inject_ready) == 0 && !delivered) idle = idle + 1;
                else idle = 0;
                if (idle > 200) fail("MESH_LIVE");
            end else idle = 0;
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        if (pend_left > 0) fail("MESH_LIVE");
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
