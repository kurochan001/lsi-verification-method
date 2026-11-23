// 2x2メッシュNoC: XY次元順ルーティングと単一VCストアアンドフォワード・ルータ。
// 1パケットはヘッダflit{dst,src,seq}+ペイロードflit{data}だが、リンクの受け渡しは
// パケット単位のFIFOスロットとして抽象化している（完結前にフォワードしない性質は同じ）。
// 出力ポート: 0=LOCAL 1=E(+x) 2=N(+y)。入力FIFO: 0=自ノード注入 1=W入力 2=S入力。
// XYで後方になる宛先（引き返しが必要なdst）は注入時に破棄する。self宛は自出口へ届く。
module router #(parameter ID = 0, BUF = 1, MUTATION = 0) (
    input wire clk, rst_n,
    input wire [11:0] loc_pkt, e_pkt, w_pkt,
    input wire loc_valid, e_valid, w_valid,
    input wire loc_out_ready, e_out_ready, w_out_ready,
    output wire loc_ready, e_ready, w_ready,
    output wire [11:0] loc_out_pkt, e_out_pkt, w_out_pkt,
    output wire loc_out_valid, e_out_valid, w_out_valid,
    output wire [2:1] pending_out
);
    reg [11:0] fifo [0:2][0:BUF-1];   // [入力ポート][スロット]。スロット0が古い
    reg [1:0]  occ [0:2];             // スロット使用数
    reg        full_r [0:2];          // 満タンの登録値（下流の受け入れ可否はこれだけを見る）
    reg [11:0] outp [0:2];            // 出力保持段
    reg        outv [0:2];
    reg [1:0]  ptr [0:2];             // 出力ポートごとのラウンドロビン・ポインタ
    localparam SLOT_BITS = BUF > 1 ? $clog2(BUF) : 1;
    integer i, k;
    localparam [1:0] XOR_BITS = MUTATION == 4 ? 2'd1 : 2'd0;  // 変異4: 経路計算のdstだけを反転

    function [1:0] route_of;          // dst宛ての次の出力ポート。引き返し不能なら2'd3
        input [1:0] dst;
        input [1:0] xor_bits;         // 変異4: 経路計算のdstだけを反転し、注入判定は正しいdstで行う
        reg [1:0] d;
        begin
            d = dst ^ xor_bits;
            route_of = 2'd3;
            if (d == ID[1:0]) route_of = 2'd0;
            else if (d[0] && !ID[0]) route_of = 2'd1;
            else if (d[1] && !ID[1]) route_of = 2'd2;
        end
    endfunction

    wire [1:0] head [0:2];
    wire [1:0] winner [0:2];
    for (genvar port = 0; port < 3; port = port + 1) begin : arbiter
        assign head[port] = occ[port] == 0 ? 2'd3 : route_of(fifo[port][0][11:10], XOR_BITS);
        wire [1:0] first = ptr[port];
        wire [1:0] second = first == 2 ? 0 : first + 2'd1;
        wire [1:0] third = second == 2 ? 0 : second + 2'd1;
        assign winner[port] = head[first] == port ? first :
                              head[second] == port ? second :
                              head[third] == port ? third : 2'd3;
        if (port > 0) begin : link_pending
            assign pending_out[port] = outv[port] || winner[port] != 2'd3;
        end
    end

    // 注入は満タンでなく、dstがXYで到達可能（+x/-yのように引き返しが必要なら破棄）なら受ける
    wire loc_ok = !full_r[0] && (!ID[0] || loc_pkt[10]) && (!ID[1] || loc_pkt[11]);
    wire e_ok = !full_r[1];
    wire w_ok = !full_r[2];
    assign loc_ready = ~full_r[0];
    assign e_ready = ~full_r[1];
    assign w_ready = ~full_r[2];
    assign loc_out_pkt = outp[0];
    assign e_out_pkt = MUTATION == 1 ? {outp[1][11:4], 4'd0} : outp[1];
    assign w_out_pkt = outp[2];
    assign loc_out_valid = outv[0];
    assign e_out_valid = outv[1];
    assign w_out_valid = outv[2];


    wire [1:0] pick0 = winner[0], pick1 = winner[1], pick2 = winner[2];
    // grant: 候補があり、保持段が空き（またはエッジ中に空く）、下流にスロットがある。
    // 変異3: LOCALへのgrantを出さない（見かけは生きたままスタックする擬似デッドロック）。
    wire g0 = MUTATION != 3 && pick0 != 2'd3 && (!outv[0] || loc_out_ready);
    // mesh出力のgrant条件は「下流にスロットがある」だけ。保持段が埋まっていても
    // 転送でそのエッジに空くなら重ねてロードできる（モデルと同一条件）。
    wire g1 = ID[0] == 1'b0 && pick1 != 2'd3 && e_out_ready;
    wire g2 = ID[1] == 1'b0 && pick2 != 2'd3 && w_out_ready;

    function [1:0] occ_next;          // ポップと押し込みの両方を反映した使用数
        input integer p;
        reg [1:0] used;
        begin
            used = occ[p];
            if ((g0 && pick0 == p[1:0]) || (g1 && pick1 == p[1:0]) || (g2 && pick2 == p[1:0]))
                used = used - 2'd1;
            if ((p == 0 && loc_valid && loc_ok) || (p == 1 && e_valid && e_ok) ||
                (p == 2 && w_valid && w_ok))
                used = used + 2'd1;
            occ_next = used;
        end
    endfunction


    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < 3; i = i + 1) begin
                occ[i] <= 0; full_r[i] <= 0; outv[i] <= 0; ptr[i] <= 0;
                for (k = 0; k < BUF; k = k + 1) fifo[i][k] <= 0;
            end
        end else begin
            // 1. ポップ（grantが選ぶのは各ポートの先頭のみ。後ろを詰める）
            if ((g0 && pick0 == 2'd0) || (g1 && pick1 == 2'd0) || (g2 && pick2 == 2'd0))
                for (k = 0; k < BUF - 1; k = k + 1) fifo[0][k] <= fifo[0][k+1];
            if ((g0 && pick0 == 2'd1) || (g1 && pick1 == 2'd1) || (g2 && pick2 == 2'd1))
                for (k = 0; k < BUF - 1; k = k + 1) fifo[1][k] <= fifo[1][k+1];
            if ((g0 && pick0 == 2'd2) || (g1 && pick1 == 2'd2) || (g2 && pick2 == 2'd2))
                for (k = 0; k < BUF - 1; k = k + 1) fifo[2][k] <= fifo[2][k+1];
            // 2. 上流（前段ルータの保持段または自ノード注入）から最新の空きスロットへ。
            //    押し込み先はポップ後の末尾。使用数と満タンフラグは1回だけ更新する。
            if (e_valid && e_ok) fifo[1][SLOT_BITS'(occ_next(1) - 2'd1)] <= e_pkt;
            if (w_valid && w_ok) fifo[2][SLOT_BITS'(occ_next(2) - 2'd1)] <= w_pkt;
            if (loc_valid && loc_ok) fifo[0][SLOT_BITS'(occ_next(0) - 2'd1)] <= loc_pkt;
            for (i = 0; i < 3; i = i + 1) begin
                occ[i] <= occ_next(i);
                full_r[i] <= occ_next(i) >= BUF[1:0];
            end
            // 4. 出力保持段: 配信で解除、grantでロード。変異2はLOCAL解除を忘れる（多重配信）
            if (MUTATION == 2) outv[0] <= outv[0] || g0;
            else outv[0] <= (outv[0] && !loc_out_ready) || g0;
            if (g0) outp[0] <= fifo[pick0][0];
            outv[1] <= (outv[1] && !e_out_ready) || g1;
            if (g1) outp[1] <= fifo[pick1][0];
            outv[2] <= (outv[2] && !w_out_ready) || g2;
            if (g2) outp[2] <= fifo[pick2][0];
            // Next service starts after the input whose grant actually transferred.
            if (g0) ptr[0] <= pick0 == 2 ? 0 : pick0 + 2'd1;
            if (g1) ptr[1] <= pick1 == 2 ? 0 : pick1 + 2'd1;
            if (g2) ptr[2] <= pick2 == 2 ? 0 : pick2 + 2'd1;
        end
    end
endmodule
