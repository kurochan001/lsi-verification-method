// -----------------------------------------------------------------------------
// mxfp4_scoreboard (付録A A.6)
//   in-order 比較。BDP は投入順 = 出力順 (LAT = 6、acc 累積はブロック昇順固定)
//   なので in-order で足りる。
//
//   [付録A A.6.2 への追加 — in 側も使う]
//     A.6.2 の骨格は in_fifo を宣言しながら out_fifo からしか取り出しておらず、
//     節タイトルの「in-order 比較」と噛み合っていない
//     (docs/spec_review_appendixA.md A-4)。本実装は入力側トランザクションから
//     first..last のブロック列を集約して 1 結果の期待値を作る。
//
//   [付録A A.6.2 からの変更 — 受け口を uvm_subscriber にする]
//     A.6.2 は uvm_tlm_analysis_fifo #(T) を使うと規定しているが、sukimasim
//     0.9.9.2 では analysis fifo へ write したトランザクションが get() 側へ
//     届かない。uvm_subscriber #(T) は同じ analysis port からの同じ write を
//     確実に受け取れるので、段ごとに薄いアダプタ subscriber を置き、照合本体
//     (on_in / on_out / on_sop) を呼ぶ構成にした。待ち合わせプロセスが要らず、
//     in-order 比較をキューで行う点は A.6.2 の趣旨どおり。
//
//   [解消済みの注意 (2026-08-21 確認) — package 関数のスコープ解決]
//     以前は ref_sop4() を mxfp4_ref_pkg::ref_sop4() と明示スコープ解決で呼ぶと
//     関数本体が実行されず型のデフォルト値 (0) が返っていたため、非修飾名で
//     呼ぶ運用にしていた。**2026-08-20 09:03 ビルドでは再現しない**
//     (package 直下 / package 内クラスのメソッドから、--enable-uvm の有無に
//     かかわらず正しい値が返る。Verilator 5.050 と一致)。
//     当時 Issue は発行しておらず、参照していた repro/pkg_scope_call_minimal.sv も
//     作られていない。非修飾名で呼ぶ運用は変えない (これで困らないため)。
//
//   照合は 2 層 (仕様書 9.2 節)。
//     ブロック内: SoP4 を整数厳密照合 (ap_sop 経由)。R1 の合否基準。
//     ブロック間: ref_dot_series で FP32 丸め + FTZ + Inf 飽和を模擬しビット照合。
//   比較は 32bit ビット厳密 (!==)。NaN は期待・実測とも NaN なら一致 (A.6.3)。
// -----------------------------------------------------------------------------

typedef class mxfp4_scoreboard;

// 入力段の受け口
class sb_in_sub extends uvm_subscriber #(bdp_in_item);
  `uvm_component_utils(sb_in_sub)
  mxfp4_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(bdp_in_item t);
    sb.on_in(t);
  endfunction
endclass

// 出力段の受け口
class sb_out_sub extends uvm_subscriber #(bdp_result_item);
  `uvm_component_utils(sb_out_sub)
  mxfp4_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(bdp_result_item t);
    sb.on_out(t);
  endfunction
endclass

// SoP4 段の受け口
class sb_sop_sub extends uvm_subscriber #(bdp_dbg_item);
  `uvm_component_utils(sb_sop_sub)
  mxfp4_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(bdp_dbg_item t);
    sb.on_sop(t);
  endfunction
endclass

class mxfp4_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(mxfp4_scoreboard)

  sb_in_sub  sub_in;
  sb_out_sub sub_out;
  sb_sop_sub sub_sop;

  env_config cfg;

  // 集約中のブロック列
  logic [135:0] a_series [$];
  logic [135:0] b_series [$];
  // 期待値キュー (in-order)
  logic [31:0]  exp_res_q [$];
  int           exp_sop_q [$];
  // 不一致報告用 (a / b / exp / act を 16 進で出す。A.6.3)
  logic [135:0] res_a_q [$];
  logic [135:0] res_b_q [$];
  logic [135:0] sop_a_q [$];
  logic [135:0] sop_b_q [$];

  int unsigned n_res_checks, n_sop_checks, n_errors;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("SB", "env_config not set")
    sub_in  = sb_in_sub ::type_id::create("sub_in",  this);
    sub_out = sb_out_sub::type_id::create("sub_out", this);
    sub_sop = sb_sop_sub::type_id::create("sub_sop", this);
    n_res_checks = 0; n_sop_checks = 0; n_errors = 0;
  endfunction

  function void connect_phase(uvm_phase phase);
    sub_in.sb  = this;
    sub_out.sb = this;
    sub_sop.sb = this;
  endfunction

  static function bit is_nan(input logic [31:0] f);
    return (f[30:23] == 8'hFF) && (f[22:0] != 23'h0);
  endfunction

  // ---------------------------------------------------------------------------
  // 入力側: SoP4 期待値を積み、first..last を集約して結果期待値を作る
  // ---------------------------------------------------------------------------
  function void on_in(bdp_in_item t);
    logic [135:0] aa [], bb [];
    exp_sop_q.push_back(ref_sop4(t.a_block, t.b_block));
    sop_a_q.push_back(t.a_block);
    sop_b_q.push_back(t.b_block);

    if (t.first) begin
      a_series.delete();
      b_series.delete();
    end
    a_series.push_back(t.a_block);
    b_series.push_back(t.b_block);

    if (t.last) begin
      aa = new[a_series.size()];
      bb = new[b_series.size()];
      foreach (a_series[i]) aa[i] = a_series[i];
      foreach (b_series[i]) bb[i] = b_series[i];
      exp_res_q.push_back(ref_dot_series_ex(aa, bb, cfg.gradual_uf));
      res_a_q.push_back(a_series[0]);
      res_b_q.push_back(b_series[0]);
    end
  endfunction

  // ---------------------------------------------------------------------------
  // 出力側: ビット厳密比較 (NaN は NaN 同士で一致)
  // ---------------------------------------------------------------------------
  function void on_out(bdp_result_item t);
    logic [31:0]  exp;
    logic [135:0] da, db;
    if (exp_res_q.size() == 0) begin
      n_errors++;
      `uvm_error("SB_UNEXPECTED",
        $sformatf("result %08h arrived with no pending expectation", t.result))
      return;
    end
    exp = exp_res_q.pop_front();
    da  = res_a_q.pop_front();
    db  = res_b_q.pop_front();
    n_res_checks++;
    if (t.result !== exp) begin
      if (!(is_nan(exp) && is_nan(t.result))) begin
        n_errors++;
        `uvm_error("SB_MISMATCH",
          $sformatf("a=%034h b=%034h exp=%08h act=%08h", da, db, exp, t.result))
      end
    end else begin
      `uvm_info("SB_MATCH", $sformatf("exp=%08h act=%08h", exp, t.result), UVM_HIGH)
    end
  endfunction

  // ---------------------------------------------------------------------------
  // SoP4 段: 整数厳密照合 (仕様書 9.2 節のブロック内層。R1 の合否基準)
  // ---------------------------------------------------------------------------
  function void on_sop(bdp_dbg_item t);
    int           exp;
    logic [135:0] da, db;
    if (exp_sop_q.size() == 0) begin
      n_errors++;
      `uvm_error("SB_UNEXPECTED",
        $sformatf("sop4 %0d arrived with no pending expectation", t.sop4))
      return;
    end
    exp = exp_sop_q.pop_front();
    da  = sop_a_q.pop_front();
    db  = sop_b_q.pop_front();
    n_sop_checks++;
    if (t.sop4 !== SOP4_W'(exp)) begin
      n_errors++;
      `uvm_error("SB_SOP_MISMATCH",
        $sformatf("a=%034h b=%034h exp=%0d act=%0d", da, db, exp, t.sop4))
    end
  endfunction

  function void check_phase(uvm_phase phase);
    // 期待値を取りこぼしていないこと (drain time 不足の検出。A-2)
    if (exp_res_q.size() != 0) begin
      n_errors++;
      `uvm_error("SB_LEFTOVER",
        $sformatf("%0d expected result(s) never observed (drain time too short?)",
                  exp_res_q.size()))
    end
    if (n_res_checks == 0 && n_sop_checks == 0) begin
      n_errors++;
      `uvm_error("SB_EMPTY", "scoreboard did not compare anything")
    end
  endfunction

  function void report_phase(uvm_phase phase);
    `uvm_info("SB", $sformatf("result checks=%0d, sop4 checks=%0d, mismatches=%0d",
                              n_res_checks, n_sop_checks, n_errors), UVM_LOW)
  endfunction
endclass
