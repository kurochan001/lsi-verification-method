// -----------------------------------------------------------------------------
// addcore_agent 一式 (付録A A.10、シナリオ R2f)
//   mxfp4_fp32_add_core を汎用 FP32 加算器として単体検証する env の driver /
//   monitor / sequencer / agent。
//
//   BDP / enc 版との違いは、**DUT が組合せ回路**であること。段レジスタが無いので
//   入力と結果は同じ時刻に確定する。したがって:
//     - 段別の analysis port は分けない (1 件の観測にまとめる)。
//     - パイプラインの drain も要らない (drain time は 0 でよいが、
//       最後の 1 件を monitor が採り切るために 2 サイクルだけ見る)。
//     - in_ready も無いので、隙間なし連続投入の検査 (A-1) は対象外。
//
//   駆動は negedge のブロッキング代入、観測は posedge (bdp / enc と同じ運用。
//   Issue #1171 のため clocking block は使わない)。
//
//   **Issue #1322 を踏まないこと。** UVM コンポーネントのタスクで
//   `if (...) begin ... for ... ; <handle>.method(); end` と書くと、
//   ループがローカルへ書いた値が失われる。ここは配列を扱わないのでループ自体が
//   不要だが、将来手を入れるときも「if の中の for + ハンドル経由の呼び出し」を
//   同じブロックに置かないこと。
// -----------------------------------------------------------------------------

// 内部指数 -> FP32 格納形式。mxfp4_bdp の pack_fp32 と同じ規約。
// **パッケージスコープに置く**こと (クラスのメソッド内に置くと #1322 の
// 条件を作りやすい。tb_fp32_add.sv の同名関数と同じ内容)。
function automatic bit [31:0] addcore_pack_fp32(
    input bit sign, input bit signed [IEXP_W-1:0] iexp, input bit [SIGNIF_W-1:0] sig);
  if (iexp >= $signed(IEXP_W'(255)))     return {sign, 8'hFF, 23'd0};
  else if (iexp <= $signed(IEXP_W'(0)))  return {sign, 31'd0};
  else                                   return {sign, iexp[7:0], sig[22:0]};
endfunction

class addcore_driver extends uvm_driver #(addcore_item);
  `uvm_component_utils(addcore_driver)

  virtual addcore_if vif;
  env_config         cfg;
  int unsigned       n_sent;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ADD_DRV", "env_config not set")
    vif = cfg.addcore_vif;
    if (vif == null) `uvm_fatal("ADD_DRV", "addcore_vif is null")
    n_sent = 0;
  endfunction

  task run_phase(uvm_phase phase);
    addcore_item tr;
    wait (vif.rst_n === 1'b0);
    wait (vif.rst_n === 1'b1);
    @(negedge vif.clk);
    vif.in_valid = 1'b0;
    forever begin
      @(negedge vif.clk);
      seq_item_port.try_next_item(tr);
      if (tr == null) begin
        vif.in_valid = 1'b0;
      end else begin
        vif.a_sign   = tr.a_sign;
        vif.a_exp    = tr.a_exp;
        vif.a_sig    = tr.a_sig;
        vif.b_sign   = tr.b_sign;
        vif.b_exp    = tr.b_exp;
        vif.b_sig    = tr.b_sig;
        vif.in_valid = 1'b1;
        seq_item_port.item_done();
        n_sent++;
      end
    end
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("ADD_DRV", $sformatf("driven %0d pair(s)", n_sent), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// addcore_monitor
//   in_valid の立っている posedge で、入力 2 つと結果を 1 件にまとめて出す。
// -----------------------------------------------------------------------------
class addcore_monitor extends uvm_monitor;
  `uvm_component_utils(addcore_monitor)

  virtual addcore_if vif;
  env_config         cfg;

  uvm_analysis_port #(addcore_obs_item) ap;

  int unsigned n_obs;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap = new("ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ADD_MON", "env_config not set")
    vif = cfg.addcore_vif;
    if (vif == null) `uvm_fatal("ADD_MON", "addcore_vif is null")
    n_obs = 0;
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      @(posedge vif.clk);
      // 駆動は negedge なので、posedge の時点で組合せは確定している。
      #1;
      if (vif.rst_n === 1'b1 && vif.in_valid === 1'b1) sample();
    end
  endtask

  task sample();
    addcore_obs_item tr;
    tr = addcore_obs_item::type_id::create("obs");
    tr.a_fp        = {vif.a_sign, vif.a_exp[7:0], vif.a_sig[22:0]};
    tr.b_fp        = {vif.b_sign, vif.b_exp[7:0], vif.b_sig[22:0]};
    tr.r_zero      = vif.r_zero;
    tr.r_carry_ovf = vif.r_carry_ovf;
    // r_zero = 1 のとき r_sig は暗黙 1 を持たない不正値なので +0 を格納する
    // (仕様書 5.6 節の注)。
    tr.r_fp        = vif.r_zero ? 32'h0000_0000
                                : addcore_pack_fp32(vif.r_sign, vif.r_exp, vif.r_sig);
    ap.write(tr);
    n_obs++;
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("ADD_MON", $sformatf("observed %0d pair(s)", n_obs), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// addcore_agent (A.5.3)
// -----------------------------------------------------------------------------
class addcore_agent extends uvm_agent;
  `uvm_component_utils(addcore_agent)

  env_config                    cfg;
  addcore_driver                drv;
  uvm_sequencer #(addcore_item) add_sequencer;
  addcore_monitor               mon;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ADD_AGT", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    mon = addcore_monitor::type_id::create("mon", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      drv           = addcore_driver::type_id::create("drv", this);
      add_sequencer = uvm_sequencer #(addcore_item)::type_id::create("add_sequencer", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.is_active == UVM_ACTIVE)
      drv.seq_item_port.connect(add_sequencer.seq_item_export);
  endfunction
endclass
