// -----------------------------------------------------------------------------
// tb_mxfp4_gemm_top
//   4x4 GEMM エンジンのテストベンチ。仕様書 9.3 節のシナリオ E3。
//     - 単位行列 x 任意行列 -> C = B 一致
//     - ランダム A / B のビット一致 (PE ごとに ref_dot_series と照合)
//     - done サイクル = 1 + KBLK + LAT の機械照合 (仕様書 11 章)
//     - KBLK 掃引
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_mxfp4_gemm_top #(
  parameter int ROWS=4, COLS=4, KBLK=4
);

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  localparam int MAX_DEPTH = (ROWS>COLS ? ROWS : COLS)*KBLK;
  localparam int ADDR_W = MAX_DEPTH>1 ? $clog2(MAX_DEPTH) : 1;

  logic clk;
  logic rst_n;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  logic               start, wr_en, wr_sel, busy, done;
  logic [ADDR_W-1:0]  wr_addr;
  logic [BLOCK_W-1:0] wr_data;
  logic [31:0]        c_o [ROWS][COLS];

  mxfp4_gemm_top #(
    .ROWS(ROWS),
    .COLS(COLS),
    .KBLK(KBLK)
  ) dut (
    .clk    (clk),
    .rst_n  (rst_n),
    .start  (start),
    .wr_en  (wr_en),
    .wr_sel (wr_sel),
    .wr_addr(wr_addr),
    .wr_data(wr_data),
    .busy   (busy),
    .done   (done),
    .c_o    (c_o)
  );

  int checks = 0;
  int errors = 0;

  task automatic chk32(input string name, input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %s : got=%h exp=%h", name, got, exp);
    end
  endtask

  task automatic chk_int(input string name, input int got, input int exp);
    checks++;
    if (got != exp) begin
      errors++;
      $display("[FAIL] %s : got=%0d exp=%0d", name, got, exp);
    end
  endtask

  // ---------------------------------------------------------------------------
  // ブロック生成
  // ---------------------------------------------------------------------------
  function automatic logic [135:0] mk_block(input logic [7:0] scale, input logic [3:0] e [32]);
    logic [127:0] el;
    for (int i = 0; i < 32; i++) el[4*i +: 4] = e[i];
    return {scale, el};
  endfunction

  function automatic logic [135:0] mk_rand(input logic [7:0] scale);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = 4'($urandom_range(0, 15));
    return mk_block(scale, e);
  endfunction

  // 要素 idx のみ +1.0 (コード 0010)、他は 0
  function automatic logic [135:0] mk_unit(input int idx);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = (i == idx) ? 4'b0010 : 4'h0;
    return mk_block(8'd127, e);
  endfunction

  // ---------------------------------------------------------------------------
  // バッファロードと起動
  // ---------------------------------------------------------------------------
  logic [135:0] a_blk [ROWS][KBLK];
  logic [135:0] b_blk [COLS][KBLK];

  task automatic load_buffers();
    @(negedge clk);
    for (int r = 0; r < ROWS; r++) begin
      for (int k = 0; k < KBLK; k++) begin
        wr_en   = 1'b1;
        wr_sel  = 1'b0;
        wr_addr = ADDR_W'(r * KBLK + k);
        wr_data = a_blk[r][k];
        @(negedge clk);
      end
    end
    for (int c = 0; c < COLS; c++) begin
      for (int k = 0; k < KBLK; k++) begin
        wr_en   = 1'b1;
        wr_sel  = 1'b1;
        wr_addr = ADDR_W'(c * KBLK + k);
        wr_data = b_blk[c][k];
        @(negedge clk);
      end
    end
    wr_en = 1'b0;
  endtask

  // start から done までのサイクル数を返す
  task automatic run_gemm(output int cycles);
    logic [31:0] previous_c [ROWS][COLS];
    previous_c = c_o;
    @(negedge clk);
    start = 1'b1;
    @(negedge clk);
    start = 1'b0;
    // start をサンプルする posedge は既に経過している。これを 1 サイクル目と
    // 数えると done は 1 + KBLK + LAT サイクル目に立つ (仕様書 8.4 節)。
    cycles = 1;
    forever begin
      @(posedge clk);
      #1;
      cycles++;
      // done is combinational; the registered result changes on the next edge.
      for (int r=0;r<ROWS;r++)
        for (int c=0;c<COLS;c++) chk32("C held before output latch",c_o[r][c],previous_c[r][c]);
      if (done) break;
      if (cycles > 500) begin
        $display("[FAIL] gemm timeout");
        errors++;
        break;
      end
    end
    // c_o は done アサートのサイクル末にラッチされるので 1 サイクル待つ
    @(posedge clk);
    #1;
  endtask

  task automatic test_reset_abort();
    int cyc;
    $display("--- E3-4: reset abort and restart with retained input buffers ---");
    @(negedge clk); start=1;
    @(negedge clk); start=0;
    repeat(2) @(negedge clk);
    rst_n=0;
    @(negedge clk); rst_n=1;
    repeat(LAT+2) begin
      @(posedge clk); #1;
      chk_int("reset cancels busy/done",int'(busy || done),0);
      for(int r=0;r<ROWS;r++)
        for(int c=0;c<COLS;c++) chk32("reset clears C",c_o[r][c],0);
    end
    run_gemm(cyc);
    chk_int("restart done cycles",cyc,1+KBLK+LAT);
    check_result("E3-4 restart");
  endtask

  // 期待値: C[r][c] = ref_dot_series(a_blk[r], b_blk[c])
  task automatic check_result(input string tag);
    logic [135:0] aa [], bb [];
    aa = new[KBLK];
    bb = new[KBLK];
    for (int r = 0; r < ROWS; r++) begin
      for (int c = 0; c < COLS; c++) begin
        for (int k = 0; k < KBLK; k++) begin
          aa[k] = a_blk[r][k];
          bb[k] = b_blk[c][k];
        end
        chk32($sformatf("%s C[%0d][%0d]", tag, r, c), c_o[r][c], ref_dot_series(aa, bb));
      end
    end
  endtask

  // ---------------------------------------------------------------------------
  // E3-1: 単位行列 x 任意行列 -> C = B
  // ---------------------------------------------------------------------------
  task automatic test_identity();
    int cyc;
    logic [135:0] aa [], bb [];
    $display("--- E3-1: identity x random ---");

    // A の行 r は「k = r の要素だけ 1.0」。他の kblk は全ゼロ。
    for (int r = 0; r < ROWS; r++)
      for (int k = 0; k < KBLK; k++)
        a_blk[r][k] = (k == 0) ? mk_unit(r) : mk_block(8'd127, '{default: 4'h0});

    for (int c = 0; c < COLS; c++)
      for (int k = 0; k < KBLK; k++)
        b_blk[c][k] = (k == 0) ? mk_rand(8'd127) : mk_block(8'd127, '{default: 4'h0});

    load_buffers();
    run_gemm(cyc);
    chk_int("E3-1 done cycles", cyc, 1 + KBLK + LAT);
    check_result("E3-1");

    // C[r][c] が B の要素 r と一致することを直接確認する
    aa = new[KBLK];
    bb = new[KBLK];
    for (int r = 0; r < ROWS; r++) begin
      for (int c = 0; c < COLS; c++) begin
        real got, exp_v;
        got   = fp32_to_real(c_o[r][c]);
        exp_v = e2m1_to_real(b_blk[c][0][4*r +: 4]);
        checks++;
        if (got != exp_v) begin
          errors++;
          $display("[FAIL] E3-1 identity C[%0d][%0d]: got=%0f exp=%0f", r, c, got, exp_v);
        end
      end
    end
  endtask

  // ---------------------------------------------------------------------------
  // E3-2: ランダム A / B のビット一致
  // ---------------------------------------------------------------------------
  task automatic test_random(input int n_iter);
    int cyc;
    $display("--- E3-2: random GEMM (%0d runs) ---", n_iter);
    for (int t = 0; t < n_iter; t++) begin
      for (int r = 0; r < ROWS; r++)
        for (int k = 0; k < KBLK; k++)
          a_blk[r][k] = mk_rand(8'($urandom_range(100, 150)));
      for (int c = 0; c < COLS; c++)
        for (int k = 0; k < KBLK; k++)
          b_blk[c][k] = mk_rand(8'($urandom_range(100, 150)));

      load_buffers();
      run_gemm(cyc);
      chk_int($sformatf("E3-2[%0d] done cycles", t), cyc, 1 + KBLK + LAT);
      check_result($sformatf("E3-2[%0d]", t));
    end
  endtask

  // ---------------------------------------------------------------------------
  // E3-3: NaN スケールの伝播
  // ---------------------------------------------------------------------------
  task automatic test_nan();
    int cyc;
    $display("--- E3-3: NaN scale propagation ---");
    for (int r = 0; r < ROWS; r++)
      for (int k = 0; k < KBLK; k++)
        a_blk[r][k] = mk_rand(8'd127);
    for (int c = 0; c < COLS; c++)
      for (int k = 0; k < KBLK; k++)
        b_blk[c][k] = mk_rand(8'd127);

    // 小構成でも有効なアドレスで NaN 伝播を確認する。
    b_blk[COLS>2 ? 2 : COLS-1][KBLK>1 ? 1 : 0] = mk_rand(8'hFF);

    load_buffers();
    run_gemm(cyc);
    check_result("E3-3");
    for (int r = 0; r < ROWS; r++)
      chk32($sformatf("E3-3 C[%0d] is qNaN", r), c_o[r][COLS>2 ? 2 : COLS-1], QNAN);
  endtask

  // ---------------------------------------------------------------------------
  // メイン
  // ---------------------------------------------------------------------------
  int n_rand;

  initial begin
    if (!$value$plusargs("N_GEMM=%d", n_rand)) n_rand = 20;

    rst_n   = 1'b0;
    start   = 1'b0;
    wr_en   = 1'b0;
    wr_sel  = 1'b0;
    wr_addr = '0;
    wr_data = '0;
    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    test_identity();
    test_random(n_rand);
    test_nan();
    test_reset_abort();

    $display("=====================================");
    $display(" tb_mxfp4_gemm_top : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

  initial begin
    #50_000_000;
    $fatal(1, "simulation timeout");
  end

endmodule
