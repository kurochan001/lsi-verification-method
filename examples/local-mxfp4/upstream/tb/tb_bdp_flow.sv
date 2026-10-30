// -----------------------------------------------------------------------------
// tb_bdp_flow
//   mxfp4_bdp_fifo (入力 FIFO + ready 拡張した BDP) のフロー制御検証。
//   仕様書 3.3 節 / 11 章 段階 7。
//
//   検証したいこと:
//     1. 上流のギャップと下流のバックプレッシャをどう入れても、内積結果が
//        ready を使わない構成と同じ (= リファレンスと一致する) こと。
//        仕様書 11 章 段階 7 の「導入時は統合パスとのビット一致回帰を必須」。
//     2. 転送が起きるまで valid とデータを保持する規約 (3.3 節) を守った
//        ソースに対して、DUT 側の SVA (p_hold / p_stall_hold /
//        p_stall_blocks_input / p_latency) がすべて成立すること。
//     3. バックプレッシャなしでは 1 ブロック/サイクルのスループットが
//        維持されること (in_ready が落ちない)。
//
//   SVA が vacuous に成立しているだけでは意味がないので、ストール発生回数・
//   FIFO 満杯回数・上流待たされ回数を数えて 0 でないことを最後に確認する。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_bdp_flow;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  localparam int DEPTH = 4;
  localparam int CNT_W = $clog2(DEPTH + 1);

  // ---------------------------------------------------------------------------
  // クロック / リセット
  // ---------------------------------------------------------------------------
  logic clk;
  logic rst_n;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // ---------------------------------------------------------------------------
  // DUT
  //   プロセスから駆動する変数に宣言時初期値は付けない (PROCASSINIT 警告)。
  // ---------------------------------------------------------------------------
  logic               in_valid;
  logic               in_ready;
  logic [BLOCK_W-1:0] a_block;
  logic [BLOCK_W-1:0] b_block;
  logic               first;
  logic               last;
  logic               out_valid;
  logic               out_ready;
  logic [31:0]        result;
  logic [CNT_W-1:0]   fifo_level_dbg;
  logic               pe_in_valid_dbg;
  logic               pe_in_ready_dbg;

  mxfp4_bdp_fifo #(
    .DEPTH(DEPTH)
  ) dut (
    .clk            (clk),
    .rst_n          (rst_n),
    .in_valid       (in_valid),
    .in_ready       (in_ready),
    .a_block        (a_block),
    .b_block        (b_block),
    .first          (first),
    .last           (last),
    .out_valid      (out_valid),
    .out_ready      (out_ready),
    .result         (result),
    .fifo_level_dbg (fifo_level_dbg),
    .pe_in_valid_dbg(pe_in_valid_dbg),
    .pe_in_ready_dbg(pe_in_ready_dbg)
  );

  // ---------------------------------------------------------------------------
  // 統計 / 期待値
  // ---------------------------------------------------------------------------
  // always ブロックから更新する変数に宣言時初期値は付けない (PROCASSINIT 警告)。
  // 初期化は initial の冒頭で行う。
  int checks;
  int errors;
  int n_stall;   // 下流が結果を受け取らずストールした回数
  int n_wait;    // 上流が FIFO 満杯で待たされた回数
  int n_full;    // FIFO が満杯だったサイクル数
  int n_res;     // 受け取った結果の数

  // 下流バックプレッシャの設定 (シナリオごとに変更)
  int bp_pct;        // out_ready を 1 にする確率 [%]
  int gap_max;       // 投入ギャップの最大サイクル数

  mailbox #(logic [31:0]) mbx_exp = new();

  task automatic chk(input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      if (errors <= 20)
        $display("[FAIL] result mismatch: got=%h exp=%h (seq %0d)", got, exp, n_res);
    end
  endtask

  // 結果の受け取りは valid && ready が成立した posedge (仕様書 3.3 節)。
  // カウンタ更新はブロッキング代入なので always ではなく initial で回す
  // (always 内のブロッキング代入は Verilator の BLKSEQ 警告になる)。
  logic [31:0] mon_exp;

  initial forever begin
    @(posedge clk);
    if (rst_n && out_valid && out_ready) begin
      n_res++;
      if (mbx_exp.try_get(mon_exp)) chk(result, mon_exp);
      else begin
        errors++;
        $display("[FAIL] unexpected result %h (no pending expectation)", result);
      end
    end
  end

  // 非 vacuous 性の観測
  initial forever begin
    @(posedge clk);
    if (rst_n) begin
      if (out_valid && !out_ready)            n_stall++;
      if (in_valid  && !in_ready)             n_wait++;
      if (fifo_level_dbg == CNT_W'(DEPTH))    n_full++;
    end
  end

  // ---------------------------------------------------------------------------
  // 下流バックプレッシャ生成
  // ---------------------------------------------------------------------------
  initial begin
    out_ready = 1'b1;
    forever begin
      @(negedge clk);
      out_ready = (32'($urandom_range(1, 100)) <= bp_pct);
    end
  end

  // ---------------------------------------------------------------------------
  // ブロック生成
  // ---------------------------------------------------------------------------
  function automatic logic [BLOCK_W-1:0] mk_rand(input logic [7:0] scale);
    logic [ELEMS_W-1:0] el;
    for (int i = 0; i < K; i++) el[4*i +: 4] = 4'($urandom_range(0, 15));
    return {scale, el};
  endfunction

  // scaled_exp が FP32 の範囲に十分収まるスケールを選ぶ。
  // 1/64 の確率で NaN スケール (0xFF) を混ぜて NaN 伝播も流す。
  function automatic logic [7:0] rand_scale();
    if ($urandom_range(0, 63) == 0) return E8M0_NAN;
    return 8'($urandom_range(100, 154));
  endfunction

  // ---------------------------------------------------------------------------
  // 駆動タスク
  //   仕様書 3.3 節の規約どおり、in_valid を立てたら転送が成立するまで
  //   valid とデータを保持する (SVA p_hold / p_hold_data が検査する)。
  // ---------------------------------------------------------------------------
  task automatic push_block(input logic [BLOCK_W-1:0] a, input logic [BLOCK_W-1:0] b,
                            input logic f, input logic l);
    @(negedge clk);
    in_valid = 1'b1;
    a_block  = a;
    b_block  = b;
    first    = f;
    last     = l;
    while (!in_ready) @(negedge clk);   // アクセプトされるまで保持
    @(posedge clk);                     // ここで転送成立
  endtask

  task automatic idle_cycles(input int n);
    if (n > 0) begin
      @(negedge clk);
      in_valid = 1'b0;
      repeat (n - 1) @(negedge clk);
    end
  endtask

  // 1 本の内積列を投入する (期待値は投入前に登録して順序を保つ)
  task automatic push_series(input int kblk);
    logic [135:0] a [];
    logic [135:0] b [];
    a = new[kblk];
    b = new[kblk];
    for (int j = 0; j < kblk; j++) begin
      a[j] = mk_rand(rand_scale());
      b[j] = mk_rand(rand_scale());
    end
    mbx_exp.put(ref_dot_series(a, b));
    for (int j = 0; j < kblk; j++) begin
      push_block(a[j], b[j], (j == 0), (j == kblk-1));
      if (gap_max > 0) idle_cycles($urandom_range(0, gap_max));
    end
    @(negedge clk);
    in_valid = 1'b0;
  endtask

  // ---------------------------------------------------------------------------
  // シナリオ
  // ---------------------------------------------------------------------------
  task automatic run_scenario(input string name, input int n_series,
                              input int ready_pct, input int max_gap);
    $display("--- %s (series=%0d, out_ready=%0d%%, gap<=%0d) ---",
             name, n_series, ready_pct, max_gap);
    bp_pct  = ready_pct;
    gap_max = max_gap;
    for (int s = 0; s < n_series; s++) push_series($urandom_range(1, 8));
    // 残りをすべて吐き出させる
    bp_pct  = 100;
    gap_max = 0;
    repeat (4 * (LAT + DEPTH)) @(negedge clk);
    checks++;
    if (mbx_exp.num() != 0) begin
      errors++;
      $display("[FAIL] %s: %0d result(s) never came out", name, mbx_exp.num());
    end
  endtask

  // バックプレッシャなしでは in_ready が落ちない (1 ブロック/サイクル)
  task automatic check_full_throughput(input int n_blocks);
    int stalled;
    $display("--- throughput: no backpressure, back-to-back ---");
    bp_pct  = 100;
    gap_max = 0;
    stalled = 0;
    fork
      begin : monitor_ready
        repeat (n_blocks) begin
          @(negedge clk);
          if (!in_ready) stalled++;
        end
      end
      begin : driver
        for (int s = 0; s < n_blocks / 4; s++) push_series(4);
      end
    join
    checks++;
    if (stalled != 0) begin
      errors++;
      $display("[FAIL] in_ready deasserted %0d time(s) without backpressure", stalled);
    end
  endtask

  int n_series;

  initial begin
    if (!$value$plusargs("N_FLOW=%d", n_series)) n_series = 300;

    checks   = 0;
    errors   = 0;
    n_stall  = 0;
    n_wait   = 0;
    n_full   = 0;
    n_res    = 0;
    bp_pct   = 100;
    gap_max  = 0;

    rst_n    = 1'b0;
    in_valid = 1'b0;
    a_block  = '0;
    b_block  = '0;
    first    = 1'b0;
    last     = 1'b0;
    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    check_full_throughput(200);

    run_scenario("F1: no backpressure",       n_series, 100, 0);
    run_scenario("F2: light backpressure",    n_series,  80, 1);
    run_scenario("F3: heavy backpressure",    n_series,  25, 3);
    run_scenario("F4: starving source",       n_series,  60, 8);

    // 非 vacuous 性: 実際にストール・FIFO 満杯を踏んでいること
    checks++;
    if (n_stall == 0) begin
      errors++;
      $display("[FAIL] no stall occurred; backpressure path untested");
    end
    checks++;
    if (n_wait == 0) begin
      errors++;
      $display("[FAIL] source was never held off; FIFO full path untested");
    end

    $display("=====================================");
    $display(" tb_bdp_flow : %0d checks, %0d errors", checks, errors);
    $display("   results=%0d  stalls=%0d  src-waits=%0d  fifo-full-cycles=%0d",
             n_res, n_stall, n_wait, n_full);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

endmodule
