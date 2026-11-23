module clock_switch #(parameter BOOT=1, MUTATION=0)(
    input  wire clk, rst_n,
    input  wire clk_a, clk_b,      // TBが4nsグリッドで生成する2系統の常発光源（8ns/12ns）
    input  wire sel,               // 要求クロック: 0=clk_a 1=clk_b
    input  wire [2:0] div,         // 分周比のリクエスト（実効比はdiv+1、1..8）
    input  wire idle,              // エンジンのアイドル示唆
    output wire engine_clk,        // ゲート＋分周したエンジンクロック
    output wire switching,         // 凍結ウィンドウ（この間engine_clkはLow保証）
    output wire sel_q,             // 実際に流している系統（デバッグ出力）
    output reg  [3:0] ratio,       // 適用中の分周比（1..8）
    output reg  [3:0] div_pend,    // 安全ウィンドウ待ちの分周比
    output reg  [3:0] phase,       // 分周カウンタ（0..ratio-1）
    output reg  [1:0] idle_run,    // 連続アイドルのエンジンサイクル（3で飽和）
    output reg        busy_hold    // idle=0のあいだ switch要求を保留中
);
    // グリッチフリーな切替: selが変わってもすぐには切り替えず、旧系統のHighが
    // 明けたサイクルからswitchingを立てて出力を止め、両系統のサンプルがLowに
    // 揃ったサイクルでsel_qとラン ENABLEを入れ替えて新系統を流し始める。
    // 分周比は idle が2エンジンサイクル続いた安全ウィンドウだけで ratio に反映し、
    // ratio と div_pend が違うあいだはphaseを0に保つ（=安全ウィンドウではエッジを
    // 出さない）。MUTATION:
    //   1=凍結せずに即切替 2=凍結解除が1サンプル早い 3=分周比をidle=1で即反映
    //   4=idle=0でも切替を受理
    reg sel_reg, run_a, run_b, sw, raw_p, engine_q;
    wire raw = (sel_q ? clk_b : clk_a) & (run_a | run_b);
    wire raw_tick = raw && !raw_p;          // 1エッジ遅れの生エッジ検出
    wire [3:0] d_next = MUTATION == 3 ? {1'b0, div} + 4'd1 : div_pend;
    wire accept = !sw && (sel != sel_q) && (MUTATION == 1 || MUTATION == 4 || idle);
    wire release_ok = sw && (MUTATION == 2 ? (!clk_a || !clk_b) : (!clk_a && !clk_b));
    // engine_clkはレジスタ出力: ゲートの遅れは1グリッド分だけで、系統入替わりで
    // 出力が断ち切られることはない（=グリッチフリーの根拠）。
    assign engine_clk = engine_q;
    assign switching = sw;
    assign sel_q = MUTATION == 1 ? sel : sel_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sel_reg <= 1'b0; run_a <= 1'b0; run_b <= 1'b0; sw <= 1'b0; raw_p <= 1'b0;
            engine_q <= 1'b0;
            ratio <= BOOT[3:0]; div_pend <= BOOT[3:0]; phase <= 4'd0;
            idle_run <= 2'd0; busy_hold <= 1'b0;
        end else begin
            engine_q <= raw & (ratio == 4'd1 || phase == ratio - 4'd1);
            div_pend <= {1'b0, div} + 4'd1;  // 安全ウィンドウ待ちの分周比は1..8で保持
            if (accept) begin
                if (MUTATION == 1) begin
                    run_a <= ~sel; run_b <= sel;
                end else if (!(sel_q ? clk_b : clk_a)) begin
                    if (sel_q) run_b <= 1'b0;
                    else run_a <= 1'b0;
                    sw <= 1'b1;
                end
            end
            if (release_ok) begin
                sel_reg <= sel;
                if (MUTATION != 1) begin
                    if (sel) run_b <= 1'b1;
                    else run_a <= 1'b1;
                end
                sw <= 1'b0;
            end
            if (busy_hold && sel == sel_q) begin
                busy_hold <= 1'b0;
            end
            if (MUTATION != 4 && !sw && (sel != sel_q) && !idle) begin
                busy_hold <= 1'b1;
            end
            if (!sw && !run_a && !run_b && sel == sel_q) begin
                if (sel) run_b <= 1'b1;
                else run_a <= 1'b1;
            end
            if (idle_run >= 2'd2 && ratio != d_next) begin
                ratio <= d_next;
            end
            raw_p <= raw;
            if (raw_tick) begin
                if (!idle) idle_run <= 2'd0;
                else if (idle_run < 2'd3) idle_run <= idle_run + 2'd1;
                if (phase >= ratio - 4'd1) phase <= 4'd0;
                else phase <= phase + 4'd1;
            end else if (!idle) begin
                idle_run <= 2'd0;
            end
            if (ratio != d_next) begin
                phase <= 4'd0;
            end else if (MUTATION == 3 && idle && phase >= ratio) begin
                phase <= 4'd0;
            end
        end
    end
endmodule
