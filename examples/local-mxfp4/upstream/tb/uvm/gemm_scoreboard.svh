// -----------------------------------------------------------------------------
// gemm_scoreboard (付録A A.9.2)
//   1 回の実行につき 2 つを照合する。
//     (1) C 行列: C[r][c] = ref_dot_series(a_mat[r], b_mat[c]) とビット一致
//     (2) done サイクル数: 1 + KBLK + LAT (仕様書 8.4 節 / 11 章)
//
//   [非 vacuous 性]
//     GEMM は「全ゼロを流すと C も期待値も全ゼロで一致する」形なので、
//     ビット一致だけでは通ってしまう (enc env で実際に踏んだ。落とし穴 4g)。
//     そこで **C に非ゼロ要素が現れたか**を数え、1 件も無ければ
//     check_phase で失敗させる。NaN 伝播の件数も出す。
//
//   受け口を uvm_subscriber にするのは他の env と同じ理由
//   (sukimasim では analysis fifo へ write したものが get() 側へ届かない)。
//
//   期待値の計算はループを伴うのでパッケージスコープの関数へ切り出す
//   (クラスのメソッド内に置くと Issue #1322 の条件を作りやすい)。
// -----------------------------------------------------------------------------

// 1 回分の期待値 C を計算する
function automatic void gemm_expect_c(gemm_item t, output bit [31:0] exp [4][4]);
  logic [135:0] aa [];
  logic [135:0] bb [];
  aa = new[4];
  bb = new[4];
  for (int r = 0; r < 4; r++) begin
    for (int c = 0; c < 4; c++) begin
      for (int k = 0; k < 4; k++) begin
        aa[k] = t.a_mat[r][k];
        bb[k] = t.b_mat[c][k];
      end
      // スコープ解決を付けずに呼ぶ (mxfp4_scoreboard.svh の注記と同じ運用)
      exp[r][c] = ref_dot_series(aa, bb);
    end
  end
endfunction

// 期待値をキューへ積む (ループを伴うのでパッケージスコープに置く)
function automatic void gemm_push_exp(input bit [31:0] exp [4][4], ref bit [31:0] q [$]);
  for (int r = 0; r < 4; r++)
    for (int c = 0; c < 4; c++)
      q.push_back(exp[r][c]);
endfunction

typedef class gemm_scoreboard;

class gemmsb_in_sub extends uvm_subscriber #(gemm_item);
  `uvm_component_utils(gemmsb_in_sub)
  gemm_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(gemm_item t);
    sb.on_in(t);
  endfunction
endclass

class gemmsb_out_sub extends uvm_subscriber #(gemm_result_item);
  `uvm_component_utils(gemmsb_out_sub)
  gemm_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(gemm_result_item t);
    sb.on_out(t);
  endfunction
endclass

class gemm_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(gemm_scoreboard)

  gemmsb_in_sub  sub_in;
  gemmsb_out_sub sub_out;

  env_config cfg;

  // 期待値キュー (in-order。1 実行につき in が 1 件、out が 1 件)
  bit [31:0] exp_q [$];       // 16 要素ずつ push する (r*4 + c の順)
  int unsigned n_pending;

  int unsigned n_check, n_mismatch;
  int unsigned n_cycle_check, n_cycle_bad;
  // 非 vacuous 性
  int unsigned n_nonzero;     // C の非ゼロ要素の総数
  int unsigned n_nan;         // C の qNaN 要素の総数

  function new(string name, uvm_component parent);
    super.new(name, parent);
    n_check = 0; n_mismatch = 0; n_cycle_check = 0; n_cycle_bad = 0;
    n_nonzero = 0; n_nan = 0; n_pending = 0;
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("GEMM_SB", "env_config not set")
    sub_in  = gemmsb_in_sub ::type_id::create("sub_in",  this);
    sub_out = gemmsb_out_sub::type_id::create("sub_out", this);
    sub_in.sb  = this;
    sub_out.sb = this;
  endfunction

  function void on_in(gemm_item t);
    bit [31:0] exp [4][4];
    gemm_expect_c(t, exp);
    gemm_push_exp(exp, exp_q);
    n_pending++;
  endfunction

  function void on_out(gemm_result_item t);
    bit [31:0] e, g;
    if (n_pending == 0) begin
      `uvm_error("GEMM_SB", "a result arrived with no pending run")
      return;
    end
    n_pending--;
    // done サイクル数 (A.9.2): 1 + KBLK + LAT
    n_cycle_check++;
    if (t.done_cycles != (1 + 4 + mxfp4_pkg::LAT)) begin
      n_cycle_bad++;
      `uvm_error("GEMM_SB_CYC", $sformatf("done cycles = %0d, expected %0d (1 + KBLK + LAT)",
                 t.done_cycles, 1 + 4 + mxfp4_pkg::LAT))
    end
    // C 行列 (16 要素)
    for (int i = 0; i < 16; i++) begin
      if (exp_q.size() == 0) begin
        `uvm_error("GEMM_SB", "expected-value queue underflow")
        return;
      end
      e = exp_q.pop_front();
      g = t.c_flat[32*i +: 32];
      n_check++;
      if (g !== e) begin
        n_mismatch++;
        `uvm_error("GEMM_SB", $sformatf("C[%0d][%0d] mismatch: got=%08h exp=%08h",
                   i / 4, i % 4, g, e))
      end
      if (g[30:23] == 8'hFF && g[22:0] != 23'd0) n_nan++;
      else if (g[30:0] != 31'd0)                 n_nonzero++;
    end
  endfunction

  function void check_phase(uvm_phase phase);
    if (n_check == 0)
      `uvm_error("GEMM_SB_EMPTY", "scoreboard did not compare anything")
    if (n_pending != 0)
      `uvm_error("GEMM_SB", $sformatf("%0d run(s) started but never produced a result", n_pending))
    // 全ゼロ同士の一致は「通った」ことにならない (落とし穴 4g)
    if (n_check > 0 && n_nonzero == 0)
      `uvm_error("GEMM_SB_VACUOUS",
        "every C element compared was zero: the comparison is vacuous (a zero DUT output matches a zero reference)")
  endfunction

  function void report_phase(uvm_phase phase);
    `uvm_info("GEMM_SB", $sformatf("C checks=%0d, mismatches=%0d | done-cycle checks=%0d, bad=%0d",
              n_check, n_mismatch, n_cycle_check, n_cycle_bad), UVM_LOW)
    if (n_check > 0)
      `uvm_info("GEMM_SB", $sformatf("C elements: non-zero=%0d (%0.1f%%)  qNaN=%0d",
                n_nonzero, 100.0 * real'(n_nonzero) / real'(n_check), n_nan), UVM_LOW)
  endfunction
endclass
