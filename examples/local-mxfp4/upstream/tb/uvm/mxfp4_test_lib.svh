// -----------------------------------------------------------------------------
// テストライブラリ (付録A A.8 / A.8.1)
//   すべての uvm_test は +UVM_TESTNAME=<test> で起動する。
//
//   [付録A A.8.1 からの変更 — drain time]
//     骨格は set_drain_time(this, 20) だが、第 2 引数はシミュレーション時間で
//     あってサイクル数ではない。timescale 1ns では 20 ns であり、LAT = 6 の
//     6 サイクル (周期 10 ns で 60 ns) に足りず、最後の内積列の out_valid が
//     立つ前に run_phase が終了して scoreboard が取りこぼす
//     (docs/spec_review_appendixA.md A-2)。
//     env_config.clk_period から (LAT + 4) x 周期 で算出する。
//
//   取りこぼしが起きていないことは scoreboard の check_phase (SB_LEFTOVER) が
//   機械的に検出する。
// -----------------------------------------------------------------------------
class mxfp4_base_test extends uvm_test;
  `uvm_component_utils(mxfp4_base_test)

  mxfp4_env  env;
  env_config cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  // 派生テストが config を上書きするためのフック
  virtual function void configure();
  endfunction

  function void build_phase(uvm_phase phase);
    int n;
    super.build_phase(phase);
    cfg = env_config::type_id::create("cfg");
    cfg.is_active      = UVM_ACTIVE;
    cfg.has_scoreboard = 1'b1;
    cfg.has_coverage   = 1'b1;
    if (!uvm_config_db#(virtual bdp_if)::get(this, "", "bdp_vif", cfg.bdp_vif))
      `uvm_fatal("TEST", "bdp_vif not set in uvm_config_db")
    if ($value$plusargs("N_ITEM=%d", n)) cfg.num_blocks = n;
    configure();
    uvm_config_db#(env_config)::set(this, "env", "cfg", cfg);
    env = mxfp4_env::type_id::create("env", this);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    uvm_phase run_ph;
    run_ph = uvm_run_phase::get();
    run_ph.phase_done.set_drain_time(this, cfg.drain_time());
    `uvm_info("TEST", $sformatf("drain time = %0t", cfg.drain_time()), UVM_LOW)
  endfunction

  function void final_phase(uvm_phase phase);
    uvm_report_server svr;
    int n_err;
    svr   = uvm_report_server::get_server();
    n_err = svr.get_severity_count(UVM_ERROR) + svr.get_severity_count(UVM_FATAL);
    $display("=====================================");
    $display(" %s : %0d UVM_ERROR/UVM_FATAL", get_type_name(), n_err);
    if (n_err == 0) $display(" *** PASS ***");
    else            $display(" *** FAIL ***");
    $display("=====================================");
  endfunction
endclass

// -----------------------------------------------------------------------------
// 単一シーケンスを流すだけのテストの共通形
// -----------------------------------------------------------------------------
virtual class mxfp4_seq_test extends mxfp4_base_test;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  pure virtual task run_seq();

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    run_seq();
    phase.drop_objection(this);
  endtask
endclass

// D1
class mxfp4_decode_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_decode_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    d1_decode_seq seq;
    seq = d1_decode_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// D2
class mxfp4_mul_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_mul_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    d2_mul_seq seq;
    seq = d2_mul_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// D3
class mxfp4_scale_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_scale_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    d3_scale_seq seq;
    seq = d3_scale_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// D4 (KBLK = 1 / 2 / 3 を掃引)
class mxfp4_bdp_acc_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_bdp_acc_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    d4_acc_seq seq;
    for (int k = 1; k <= 3; k++) begin
      seq = d4_acc_seq::type_id::create("seq");
      seq.kblk = k;
      seq.start(env.bdp_agt.bdp_sequencer);
    end
  endtask
endclass

// R1
class mxfp4_rand_sop_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_rand_sop_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    r1_rand_seq seq;
    seq   = r1_rand_seq::type_id::create("seq");
    seq.n = cfg.num_blocks;
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// R2a
class mxfp4_r2a_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_r2a_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    r2a_scaled_exp_seq seq;
    seq   = r2a_scaled_exp_seq::type_id::create("seq");
    seq.n = cfg.num_blocks;
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// R2b
class mxfp4_r2b_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_r2b_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    r2b_ovf_seq seq;
    seq = r2b_ovf_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// R2c
class mxfp4_r2c_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_r2c_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    r2c_uf_seq seq;
    seq = r2c_uf_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// R2d
class mxfp4_r2d_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_r2d_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    r2d_bound_seq seq;
    seq = r2d_bound_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// E1
class mxfp4_allzero_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_allzero_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    e1_allzero_seq seq;
    seq = e1_allzero_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// E2
class mxfp4_cancel_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_cancel_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task run_seq();
    e2_cancel_seq seq;
    seq = e2_cancel_seq::type_id::create("seq");
    seq.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass

// -----------------------------------------------------------------------------
// BDP レベルのレグレッション (A.11.4 のカバレッジ閉包を単一シミュレータで代替)
//   sukimasim はテスト横断のカバレッジマージを持たないため、全シーケンスを
//   1 テストで流して cg_bdp_* の閉包を確認する。
// -----------------------------------------------------------------------------
class mxfp4_bdp_regress_test extends mxfp4_seq_test;
  `uvm_component_utils(mxfp4_bdp_regress_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  function void configure();
    cfg.check_coverage = 1'b1;
  endfunction

  task run_seq();
    d1_decode_seq      s_d1;
    d2_mul_seq         s_d2;
    d3_scale_seq       s_d3;
    d4_acc_seq         s_d4;
    r1_rand_seq        s_r1;
    r2a_scaled_exp_seq s_r2a;
    r2b_ovf_seq        s_r2b;
    r2c_uf_seq         s_r2c;
    r2d_bound_seq      s_r2d;
    e1_allzero_seq     s_e1;
    e2_cancel_seq      s_e2;

    s_d1 = d1_decode_seq::type_id::create("s_d1");
    s_d1.start(env.bdp_agt.bdp_sequencer);
    s_d2 = d2_mul_seq::type_id::create("s_d2");
    s_d2.start(env.bdp_agt.bdp_sequencer);
    s_d3 = d3_scale_seq::type_id::create("s_d3");
    s_d3.start(env.bdp_agt.bdp_sequencer);
    for (int k = 1; k <= 3; k++) begin
      s_d4 = d4_acc_seq::type_id::create("s_d4");
      s_d4.kblk = k;
      s_d4.start(env.bdp_agt.bdp_sequencer);
    end
    s_r1   = r1_rand_seq::type_id::create("s_r1");
    s_r1.n = cfg.num_blocks;
    s_r1.start(env.bdp_agt.bdp_sequencer);
    s_r2a   = r2a_scaled_exp_seq::type_id::create("s_r2a");
    s_r2a.n = cfg.num_blocks;
    s_r2a.start(env.bdp_agt.bdp_sequencer);
    s_r2b = r2b_ovf_seq::type_id::create("s_r2b");
    s_r2b.start(env.bdp_agt.bdp_sequencer);
    s_r2c = r2c_uf_seq::type_id::create("s_r2c");
    s_r2c.start(env.bdp_agt.bdp_sequencer);
    s_r2d = r2d_bound_seq::type_id::create("s_r2d");
    s_r2d.start(env.bdp_agt.bdp_sequencer);
    s_e1 = e1_allzero_seq::type_id::create("s_e1");
    s_e1.start(env.bdp_agt.bdp_sequencer);
    s_e2 = e2_cancel_seq::type_id::create("s_e2");
    s_e2.start(env.bdp_agt.bdp_sequencer);
  endtask
endclass
