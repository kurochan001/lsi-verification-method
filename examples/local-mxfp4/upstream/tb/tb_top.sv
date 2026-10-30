// -----------------------------------------------------------------------------
// tb_top
//   仕様書 9.1 節のクラスベーステストベンチ。UVM 非依存だが、sukimasim の
//   言語機能検証を兼ねてクラス・mailbox・制約付きランダム・covergroup・SVA を
//   意図的に使用する (仕様書 10 章の対応表)。
//
//     ├─ clk/rst 生成、DUT インスタンス (mxfp4_bdp / quant_encoder)
//     ├─ class BlockPairItem … 制約付きランダムでブロックペアを生成
//     ├─ class BlockGen      … 内積列を組み立て mailbox へ
//     ├─ class Driver        … mailbox から受け取り DUT へ駆動 + 期待値生成
//     ├─ class Monitor       … 出力を観測し mailbox へ
//     ├─ class Scoreboard    … リファレンスモデルとビット照合
//     ├─ covergroup          … 9.4 節
//     └─ SVA                 … 9.5 節 (tb/mxfp4_bdp_sva.sv から bind)
//
//   covergroup は `MXFP4_COVERAGE` が定義されているときだけ有効になる
//   (Verilator は covergroup 未対応のため)。sukimasim では
//     sukimasim -assert +define+MXFP4_COVERAGE -top tb_top ...
//   で実行する。
//
//   [仕様書 9.4 節からの修正 — サンプルタイミング]
//     9.4 節の cg_bdp は cp_sop_* と cp_exp_region も含めて
//     `@(posedge clk iff in_valid)` でサンプルしているが、sop4_dbg は S3、
//     exp_internal_dbg は S5 の信号なので、投入時刻にサンプルすると 3〜4 サイクル
//     前のデータを拾ってしまい cross や相関が崩れる。本 TB は covergroup を
//     入力段 / SoP4 段 / 指数段の 3 つに分割し、それぞれ正しい段の valid で
//     サンプルする。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_top;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

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
  // DUT 1: mxfp4_bdp
  // ---------------------------------------------------------------------------
  // プロセスから駆動する変数に宣言時初期値は付けない (PROCASSINIT 警告になる)。
  // 初期化はリセットシーケンスで行う。
  logic                     in_valid;
  logic                     in_ready;
  logic [BLOCK_W-1:0]       a_block;
  logic [BLOCK_W-1:0]       b_block;
  logic                     first;
  logic                     last;
  logic                     out_valid;
  logic [31:0]              result;
  logic signed [SOP4_W-1:0] sop4_dbg;
  logic                     sop_valid_dbg;
  logic signed [IEXP_W-1:0] exp_internal_dbg;
  logic                     exp_valid_dbg;

  mxfp4_bdp dut (
    .clk             (clk),
    .rst_n           (rst_n),
    .in_valid        (in_valid),
    .in_ready        (in_ready),
    .a_block         (a_block),
    .b_block         (b_block),
    .first           (first),
    .last            (last),
    .out_valid       (out_valid),
    .out_ready       (1'b1),          // 本 TB はバックプレッシャを掛けない
    .result          (result),
    .sop4_dbg        (sop4_dbg),
    .sop_valid_dbg   (sop_valid_dbg),
    .exp_internal_dbg(exp_internal_dbg),
    .exp_valid_dbg   (exp_valid_dbg),
    .gradual_uf_dbg  ()
  );

  // ---------------------------------------------------------------------------
  // DUT 2: quant_encoder
  // ---------------------------------------------------------------------------
  logic                           enc_valid_i;
  logic [31:0]                    enc_v [K];
  logic [BLOCK_W-1:0]             enc_blk;
  logic                           enc_valid_o;
  logic signed [SCALED_EXP_W-1:0] enc_erel [K];
  logic [2:0]                     enc_mag3 [K];
  logic                           enc_tie  [K];
  logic                           enc_q_valid;

  quant_encoder enc (
    .clk      (clk),
    .rst_n    (rst_n),
    .in_valid (enc_valid_i),
    .v_i      (enc_v),
    .blk_o    (enc_blk),
    .out_valid(enc_valid_o),
    .e_rel_dbg      (enc_erel),
    .mag3_dbg       (enc_mag3),
    .tie_hit_dbg    (enc_tie),
    .quant_valid_dbg(enc_q_valid)
  );

  // ---------------------------------------------------------------------------
  // スコアボード集計
  // ---------------------------------------------------------------------------
  int checks = 0;
  int errors = 0;

  // ===========================================================================
  // covergroup (仕様書 9.4 節)
  // ===========================================================================
`ifdef MXFP4_COVERAGE

  covergroup cg_bdp_in @(posedge clk iff (rst_n && in_valid));
    cp_a_scale: coverpoint a_block[BLOCK_W-1 -: 8] {
      bins zero = {8'h00};
      bins mid  = {[8'h01:8'hFE]};
      bins nan  = {8'hFF};
    }
    cp_b_scale: coverpoint b_block[BLOCK_W-1 -: 8] {
      bins zero = {8'h00};
      bins mid  = {[8'h01:8'hFE]};
      bins nan  = {8'hFF};
    }
    cp_first: coverpoint first;
    cp_last:  coverpoint last;
    // 1 ブロック列 (first & last 同時) を含む全 4 組合せ
    cp_first_last: cross cp_first, cp_last;
  endgroup

  covergroup cg_bdp_sop @(posedge clk iff (rst_n && sop_valid_dbg));
    cp_sop_sign: coverpoint sop4_dbg[SOP4_W-1];
    cp_sop_zero: coverpoint (sop4_dbg == '0);
  endgroup

  covergroup cg_bdp_exp @(posedge clk iff (rst_n && exp_valid_dbg));
    cp_exp_region: coverpoint exp_internal_dbg {
      bins uf   = {[-300:0]};
      bins norm = {[1:254]};
      bins ovf  = {[255:400]};
    }
  endgroup

  // cg_enc は要素ごとにサンプルするため明示 sample() 方式
  logic [2:0]                     cov_mag3;
  logic signed [SCALED_EXP_W-1:0] cov_erel;
  bit                             cov_tie;

  covergroup cg_enc;
    cp_code: coverpoint cov_mag3 { bins all_codes[] = {[0:7]}; }
    cp_erel: coverpoint cov_erel {
      // 仕様書の bins low = {[-10:-3]} では実際の値域 (-254..2) を覆えないため
      // 下限を拡張した。
      bins low  = {[-300:-3]};
      bins b_m2 = {-2};
      bins b_m1 = {-1};
      bins b0   = {0};
      bins b1   = {1};
      bins b2   = {2};
      // e_rel = exp_field(Vi) - X_biased、X_biased = max(0, amax_exp - 2)、
      // exp_field(Vi) <= amax_exp より quant_encoder では e_rel >= 3 は
      // 構造的に発生しない (README 参照)。除外 bin として明記する。
      ignore_bins hi = {[3:10]};
    }
    cp_tie: coverpoint cov_tie;
  endgroup

  cg_bdp_in  cg_in_i;
  cg_bdp_sop cg_sop_i;
  cg_bdp_exp cg_exp_i;
  cg_enc     cg_enc_i;

  always @(posedge clk) begin
    if (rst_n && enc_q_valid) begin
      for (int i = 0; i < K; i++) begin
        cov_mag3 = enc_mag3[i];
        cov_erel = enc_erel[i];
        cov_tie  = enc_tie[i];        // タイ判定は RTL 側 (仕様書 7.6 節の観測ポート)
        cg_enc_i.sample();
      end
    end
  end
`endif

  // ===========================================================================
  // トランザクション (仕様書 9.1 節 BlockGen の rand フィールド)
  // ===========================================================================
  class BlockPairItem;
    rand logic [7:0]  a_scale;
    rand logic [7:0]  b_scale;
    // Packed lanes preserve 32 independent nibbles and avoid the generated
    // undriven rand-array temporary in Verilator 5.052.
    rand logic [31:0][3:0] a_el;
    rand logic [31:0][3:0] b_el;
    // シナリオ選択。covergroup の全 bin を踏むために制約で使い分ける。
    rand int unsigned mode;

    // 列の組み立て時に BlockGen が決める (module の first/last と名前が
    // 衝突しないよう is_ を付ける)
    bit is_first;
    bit is_last;

    constraint c_mode {
      mode dist { 0 := 60, 1 := 6, 2 := 5, 3 := 5, 4 := 8, 5 := 8, 6 := 8 };
    }

    constraint c_scale {
      // 0: 通常域 / 1: 下端 0x00 / 2,3: NaN / 4: オーバーフロー方向
      // 5: アンダーフロー方向 / 6: 全ゼロブロック (post_randomize で要素を潰す)
      (mode == 0) -> (a_scale inside {[8'd100:8'd154]} && b_scale inside {[8'd100:8'd154]});
      (mode == 1) -> (a_scale == 8'h00 && b_scale == 8'h00);
      (mode == 2) -> (a_scale == 8'hFF);
      (mode == 3) -> (b_scale == 8'hFF);
      (mode == 4) -> (a_scale inside {[8'd240:8'd254]} && b_scale inside {[8'd240:8'd254]});
      (mode == 5) -> (a_scale inside {[8'd0:8'd20]}    && b_scale inside {[8'd0:8'd20]});
      (mode == 6) -> (a_scale inside {[8'd100:8'd154]} && b_scale inside {[8'd100:8'd154]});
      // NaN は mode 2/3 でのみ出す (それ以外で偶発的に混ざらないようにする)
      (mode != 2) -> (a_scale != 8'hFF);
      (mode != 3) -> (b_scale != 8'hFF);
    }

    function void post_randomize();
      if (mode == 6) begin
        // 全ゼロブロック: SoP4 = 0 を踏ませる (cp_sop_zero)
        foreach (a_el[i]) a_el[i] = 4'h0;
      end
    endfunction

    function logic [135:0] get_a();
      logic [127:0] el;
      foreach (a_el[i]) el[4*i +: 4] = a_el[i];
      return {a_scale, el};
    endfunction

    function logic [135:0] get_b();
      logic [127:0] el;
      foreach (b_el[i]) el[4*i +: 4] = b_el[i];
      return {b_scale, el};
    endfunction
  endclass

  // ===========================================================================
  // Generator / Driver / Monitor / Scoreboard
  // ===========================================================================
  bit gen_done = 1'b0;
  int n_series_total = 0;

  class BlockGen;
    mailbox #(BlockPairItem) mbx;
    int n_series;

    function new(mailbox #(BlockPairItem) m, int n);
      mbx      = m;
      n_series = n;
    endfunction

    task run();
      BlockPairItem it;
      int len;
      for (int s = 0; s < n_series; s++) begin
        // 1 ブロック列 (first & last 同時) も必ず混ぜる
        len = $urandom_range(1, 3);
        for (int j = 0; j < len; j++) begin
          it = new();
          if (!it.randomize())
            $fatal(1, "BlockGen: randomize() failed");
          it.is_first = (j == 0);
          it.is_last  = (j == len - 1);
          mbx.put(it);
        end
        n_series_total++;
      end
      gen_done = 1'b1;
    endtask
  endclass

  class Driver;
    mailbox #(BlockPairItem) mbx_in;
    mailbox #(logic [31:0])  mbx_exp;

    function new(mailbox #(BlockPairItem) mi, mailbox #(logic [31:0]) me);
      mbx_in  = mi;
      mbx_exp = me;
    endfunction

    task run();
      BlockPairItem it;
      logic [135:0] a_q [$], b_q [$];
      logic [135:0] aa [], bb [];

      while (!(gen_done && mbx_in.num() == 0)) begin
        mbx_in.get(it);
        @(negedge clk);
        in_valid = 1'b1;
        a_block  = it.get_a();
        b_block  = it.get_b();
        first    = it.is_first;
        last     = it.is_last;

        if (it.is_first) begin
          a_q.delete();
          b_q.delete();
        end
        a_q.push_back(it.get_a());
        b_q.push_back(it.get_b());

        if (it.is_last) begin
          // 期待値はリファレンスモデルで生成する (仕様書 9.2 節)
          aa = new[a_q.size()];
          bb = new[b_q.size()];
          foreach (a_q[i]) aa[i] = a_q[i];
          foreach (b_q[i]) bb[i] = b_q[i];
          mbx_exp.put(ref_dot_series(aa, bb));
        end
      end

      @(negedge clk);
      in_valid = 1'b0;
      first    = 1'b0;
      last     = 1'b0;
    endtask
  endclass

  class Monitor;
    mailbox #(logic [31:0]) mbx_out;

    function new(mailbox #(logic [31:0]) m);
      mbx_out = m;
    endfunction

    task run();
      forever begin
        @(posedge clk);
        if (rst_n && out_valid) mbx_out.put(result);
      end
    endtask
  endclass

  class Scoreboard;
    mailbox #(logic [31:0]) mbx_exp, mbx_mon;
    int n_expected;

    function new(mailbox #(logic [31:0]) me, mailbox #(logic [31:0]) mm, int n);
      mbx_exp    = me;
      mbx_mon    = mm;
      n_expected = n;
    endfunction

    task run();
      logic [31:0] e, g;
      for (int t = 0; t < n_expected; t++) begin
        mbx_exp.get(e);
        mbx_mon.get(g);
        checks++;
        if (g !== e) begin
          errors++;
          $display("[FAIL] Scoreboard series[%0d] : got=%h exp=%h", t, g, e);
        end
      end
    endtask
  endclass

  // ===========================================================================
  // エンコーダ側スティミュラス (cg_enc を埋める)
  // ===========================================================================
  function automatic logic [31:0] rand_fp32_enc(input int emin, input int emax);
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'($urandom_range(emin, emax));
    f[22:0]  = 23'($urandom);
    return f;
  endfunction

  // guard = 1 / sticky = 0 の値。binade 内の中点なのでタイ点になる。
  function automatic logic [31:0] tie_fp32(input int emin, input int emax);
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'($urandom_range(emin, emax));
    f[22]    = 1'($urandom_range(0, 1));
    f[21]    = 1'b1;
    f[20:0]  = 21'd0;
    return f;
  endfunction

  task automatic enc_drive(input logic [31:0] v [K]);
    @(negedge clk);
    enc_valid_i = 1'b1;
    for (int i = 0; i < K; i++) enc_v[i] = v[i];
    @(negedge clk);
    enc_valid_i = 1'b0;
    repeat (ENC_LAT - 1) @(posedge clk);
    #1;
    checks++;
    if (!enc_valid_o) begin
      errors++;
      $display("[FAIL] enc out_valid not asserted at ENC_LAT=%0d", ENC_LAT);
    end
  endtask

  task automatic enc_stimulus(input int n);
    logic [31:0] v [K];
    int emin, emax;
    for (int t = 0; t < n; t++) begin
      emin = $urandom_range(1, 240);
      emax = emin + $urandom_range(0, 12);
      if (emax > 254) emax = 254;
      for (int i = 0; i < K; i++) begin
        case ($urandom_range(0, 5))
          0:       v[i] = 32'h0000_0000;                 // ゼロ (DAZ)
          1:       v[i] = tie_fp32(emin, emax);          // タイ点 (cp_tie)
          2:       v[i] = {1'b0, 8'h00, 23'($urandom)};  // デノーマル (DAZ)
          default: v[i] = rand_fp32_enc(emin, emax);
        endcase
      end
      enc_drive(v);
      checks++;
      if (enc_blk !== ref_encode_block(v)) begin
        errors++;
        $display("[FAIL] enc block[%0d] : got=%h exp=%h", t, enc_blk, ref_encode_block(v));
      end
    end
  endtask

  // ===========================================================================
  // メイン
  // ===========================================================================
  mailbox #(BlockPairItem) mbx_gen;
  mailbox #(logic [31:0])  mbx_exp;
  mailbox #(logic [31:0])  mbx_mon;

  BlockGen    gen;
  Driver      drv;
  Monitor     mon;
  Scoreboard  sb;

  int n_series, n_enc;

  initial begin
    if (!$value$plusargs("N_SERIES=%d", n_series)) n_series = 300;
    if (!$value$plusargs("N_ENC=%d",    n_enc))    n_enc    = 100;

`ifdef MXFP4_COVERAGE
    cg_in_i  = new();
    cg_sop_i = new();
    cg_exp_i = new();
    cg_enc_i = new();
`endif

    mbx_gen = new();
    mbx_exp = new();
    mbx_mon = new();

    gen = new(mbx_gen, n_series);
    drv = new(mbx_gen, mbx_exp);
    mon = new(mbx_mon);
    sb  = new(mbx_exp, mbx_mon, n_series);

    rst_n       = 1'b0;
    in_valid    = 1'b0;
    a_block     = '0;
    b_block     = '0;
    first       = 1'b0;
    last        = 1'b0;
    enc_valid_i = 1'b0;
    for (int i = 0; i < K; i++) enc_v[i] = 32'h0;
    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    // --- BDP: クラスベースの制約付きランダム回帰 ---
    $display("--- tb_top: BDP constrained-random (%0d series) ---", n_series);
    fork
      gen.run();
      drv.run();
      mon.run();
    join_none
    sb.run();

    // out_valid が last の数を超えて立っていないこと
    // (SVA の逆向きプロパティの代わり。mxfp4_bdp_sva.sv 参照)。
    // Monitor を動かしたまま余剰を吸わせてから停止する。
    repeat (LAT + 2) @(posedge clk);
    disable fork;
    checks++;
    if (mbx_mon.num() != 0) begin
      errors++;
      $display("[FAIL] extra out_valid: %0d leftover result(s)", mbx_mon.num());
    end

    // --- Encoder: cg_enc を埋めるスティミュラス ---
    $display("--- tb_top: encoder stimulus (%0d blocks) ---", n_enc);
    enc_stimulus(n_enc);

`ifdef MXFP4_COVERAGE
    $display("--- functional coverage ---");
    $display("  cg_bdp_in  : %0.2f %%", cg_in_i.get_coverage());
    $display("  cg_bdp_sop : %0.2f %%", cg_sop_i.get_coverage());
    $display("  cg_bdp_exp : %0.2f %%", cg_exp_i.get_coverage());
    $display("  cg_enc     : %0.2f %%", cg_enc_i.get_coverage());
    checks++;
    if (cg_in_i.get_coverage()  < 100.0 || cg_sop_i.get_coverage() < 100.0 ||
        cg_exp_i.get_coverage() < 100.0 || cg_enc_i.get_coverage() < 100.0) begin
      errors++;
      $display("[FAIL] functional coverage below 100%% (see bins above)");
    end
`endif

    $display("=====================================");
    $display(" tb_top : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

  initial begin
    #100_000_000;
    $fatal(1, "simulation timeout");
  end

endmodule
