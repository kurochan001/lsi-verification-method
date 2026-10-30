// -----------------------------------------------------------------------------
// enc_test_lib
//   quant_encoder レベルの uvm_test (付録A A.8、対応表の mxfp4_quant_test /
//   mxfp4_r3_test)。トップは hw_enc_top。
//
//     make sim-uvm-enc UVM_TEST=mxfp4_quant_test
//     make sim-uvm-enc UVM_TEST=mxfp4_r3_test
//
//   drain time は BDP 版と同じく env_config から算出するが、パイプライン段数が
//   ENC_LAT = 5 なので余裕込みで (ENC_LAT + 4) x 周期 を使う (指摘 A-2)。
//
//   `enc_base_test` は基底で、単体で走らせるものではない (シーケンスを
//   起動しないので ENC_SB_EMPTY が出る)。
// -----------------------------------------------------------------------------
class enc_base_test extends uvm_test;
  `uvm_component_utils(enc_base_test)

  enc_env    env;
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
    if (!uvm_config_db#(virtual enc_if)::get(this, "", "enc_vif", cfg.enc_vif))
      `uvm_fatal("ENC_TEST", "enc_vif not set in uvm_config_db")
    if ($value$plusargs("N_ITEM=%d", n)) cfg.num_blocks = n;
    configure();
    uvm_config_db#(env_config)::set(this, "env", "cfg", cfg);
    env = enc_env::type_id::create("env", this);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    uvm_phase run_ph;
    run_ph = uvm_run_phase::get();
    run_ph.phase_done.set_drain_time(this, cfg.enc_drain_time());
    `uvm_info("ENC_TEST", $sformatf("drain time = %0t", cfg.enc_drain_time()), UVM_LOW)
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
// mxfp4_quant_test (D5)
//   タイ 7 点 ±1ulp / クランプ / 7.5 節のエッジケースを directed で流す。
//   カバレッジ閉包は要求しない (directed だけでは cg_enc は閉じない)。
// -----------------------------------------------------------------------------
class mxfp4_quant_test extends enc_base_test;
  `uvm_component_utils(mxfp4_quant_test)

  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  task run_phase(uvm_phase phase);
    d5b_tie_seq   tie_seq;
    enc_edge_seq  edge_seq;
    phase.raise_objection(this);
    tie_seq = d5b_tie_seq::type_id::create("tie_seq");
    tie_seq.start(env.enc_agt.enc_sequencer);
    edge_seq = enc_edge_seq::type_id::create("edge_seq");
    edge_seq.start(env.enc_agt.enc_sequencer);
    phase.drop_objection(this);
  endtask
endclass

// -----------------------------------------------------------------------------
// mxfp4_r3_test (R3)
//   ランダム往復。scoreboard がブロック単位のビット照合を行い、
//   クランプ / フラッシュ率を report_phase でログする (9.3 節 R3 の要件)。
// -----------------------------------------------------------------------------
class mxfp4_r3_test extends enc_base_test;
  `uvm_component_utils(mxfp4_r3_test)

  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  task run_phase(uvm_phase phase);
    r3_rand_seq seq;
    phase.raise_objection(this);
    seq = r3_rand_seq::type_id::create("seq");
    seq.n_blocks = cfg.num_blocks;
    seq.start(env.enc_agt.enc_sequencer);
    phase.drop_objection(this);
  endtask
endclass

// -----------------------------------------------------------------------------
// mxfp4_enc_regress_test
//   directed + random を続けて流し、cg_enc の 100% 閉包まで要求する
//   (BDP 側の mxfp4_bdp_regress_test に相当)。
// -----------------------------------------------------------------------------
class mxfp4_enc_regress_test extends enc_base_test;
  `uvm_component_utils(mxfp4_enc_regress_test)

  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  function void configure();
    cfg.check_coverage = 1'b1;
  endfunction

  task run_phase(uvm_phase phase);
    d5b_tie_seq  tie_seq;
    enc_edge_seq edge_seq;
    r3_rand_seq  rand_seq;
    phase.raise_objection(this);
    tie_seq = d5b_tie_seq::type_id::create("tie_seq");
    tie_seq.start(env.enc_agt.enc_sequencer);
    edge_seq = enc_edge_seq::type_id::create("edge_seq");
    edge_seq.start(env.enc_agt.enc_sequencer);
    rand_seq = r3_rand_seq::type_id::create("rand_seq");
    rand_seq.n_blocks = cfg.num_blocks;
    rand_seq.start(env.enc_agt.enc_sequencer);
    phase.drop_objection(this);
  endtask
endclass
