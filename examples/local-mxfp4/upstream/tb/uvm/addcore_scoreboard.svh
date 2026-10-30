// -----------------------------------------------------------------------------
// addcore_scoreboard (付録A A.10)
//   方針 3 (広幅整数で厳密加算してから 1 回だけ RNE) の
//   mxfp4_ref_pkg::ref_fp32_add_fp32() と 32bit ビット厳密に照合する。
//   合否基準は仕様書 9.3 節 R2f のとおりビット一致 100%。
//
//   組合せ DUT なので in-order のキューは要らない。monitor が入力と結果を
//   1 件にまとめて出すので、受け取った時点で照合できる。
//
//   [非 vacuous 性のログ]
//     R2f が意味を持つのは「桁上げ + sticky の帯」を実際に踏んだときだけ
//     なので、指数差の分布と完全相殺の件数を report_phase に出す。
//     enc env では全ゼロ入力を全ゼロ期待値と比べて **mismatch 0 のまま
//     素通り**した実例があるので、この env でも「何を踏んだか」を数字で
//     見えるようにしておく (README の落とし穴 4g)。
//
//   受け口を uvm_subscriber にするのは BDP / enc 版と同じ理由
//   (sukimasim では analysis fifo へ write したものが get() 側へ届かない)。
// -----------------------------------------------------------------------------

typedef class addcore_scoreboard;

class addsb_sub extends uvm_subscriber #(addcore_obs_item);
  `uvm_component_utils(addsb_sub)
  addcore_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(addcore_obs_item t);
    sb.on_obs(t);
  endfunction
endclass

class addcore_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(addcore_scoreboard)

  addsb_sub  sub;
  env_config cfg;

  int unsigned n_check, n_mismatch;
  // 非 vacuous 性の裏付け
  int unsigned n_cancel;      // r_zero = 1 (完全相殺)
  int unsigned n_carry_ovf;   // 丸めオーバーフロー痕跡
  int          d_min, d_max;  // 観測した指数差の範囲
  int unsigned n_band;        // 指数差 1..30 (桁上げ + sticky の帯)

  function new(string name, uvm_component parent);
    super.new(name, parent);
    n_check = 0; n_mismatch = 0; n_cancel = 0; n_carry_ovf = 0;
    n_band  = 0; d_min = 1000; d_max = -1000;
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ADD_SB", "env_config not set")
    sub    = addsb_sub::type_id::create("sub", this);
    sub.sb = this;
  endfunction

  function void on_obs(addcore_obs_item t);
    bit [31:0] exp;
    int        d;
    // スコープ解決を付けずに呼ぶ (mxfp4_scoreboard.svh の注記と同じ運用)
    exp = ref_fp32_add_fp32(t.a_fp, t.b_fp);
    n_check++;
    if (t.r_fp !== exp) begin
      n_mismatch++;
      `uvm_error("ADD_SB", $sformatf("mismatch: %08h + %08h -> got=%08h exp=%08h (zero=%0b covf=%0b)",
                 t.a_fp, t.b_fp, t.r_fp, exp, t.r_zero, t.r_carry_ovf))
    end
    if (t.r_zero)      n_cancel++;
    if (t.r_carry_ovf) n_carry_ovf++;
    d = int'(t.b_fp[30:23]) - int'(t.a_fp[30:23]);
    if (d < d_min) d_min = d;
    if (d > d_max) d_max = d;
    if (d >= 1 && d <= 30) n_band++;
  endfunction

  function void check_phase(uvm_phase phase);
    if (n_check == 0)
      `uvm_error("ADD_SB_EMPTY", "scoreboard did not compare anything")
    // R2f の意味は桁上げ + sticky の帯を踏むことにある。踏んでいなければ
    // 「通った」ことに価値がないので、明示的に失敗させる。
    if (cfg.check_b2b && n_check > 0 && n_band == 0)
      `uvm_error("ADD_SB_BAND",
        "no pair with an exponent difference of 1..30 was seen: the carry+sticky rounding path (R2f) was never exercised")
    // 完全相殺 (r_zero = 1 かつ +0) も R2f の合否基準に入っている (仕様書 9.3 節)。
    // **制約付きランダムだけに頼らないこと** — sukimasim 0.9.9.2 は dist の重みを
    // 無視することがあり (Issue #1323)、完全相殺のモードが一度も生成されない。
    // r2f_directed_seq が確実に踏むようにしてあるので、ここで実際に踏んだかを見る。
    if (cfg.check_b2b && n_check > 0 && n_cancel == 0)
      `uvm_error("ADD_SB_CANCEL",
        "no full cancellation (r_zero) was seen: the R2f cancellation criterion was never exercised")
  endfunction

  function void report_phase(uvm_phase phase);
    `uvm_info("ADD_SB", $sformatf("checks=%0d, mismatches=%0d", n_check, n_mismatch), UVM_LOW)
    if (n_check > 0)
      `uvm_info("ADD_SB", $sformatf(
        "exp-diff range=[%0d, %0d]  in the 1..30 band=%0d (%0.1f%%)  cancellations=%0d  carry_ovf=%0d",
        d_min, d_max, n_band, 100.0 * real'(n_band) / real'(n_check), n_cancel, n_carry_ovf), UVM_LOW)
  endfunction
endclass
