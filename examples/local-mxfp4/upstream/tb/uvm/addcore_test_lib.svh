// -----------------------------------------------------------------------------
// addcore_test_lib
//   加算器単体レベルの uvm_test (付録A A.10、シナリオ R2f)。トップは hw_add_top。
//
//     make sim-uvm-add UVM_TEST=mxfp4_r2f_test
//
//   DUT が組合せなので drain time はほぼ不要だが、最後の 1 件を monitor が
//   posedge で採り切るために 2 サイクルだけ見る。
//
//   `addcore_base_test` は基底で、単体で走らせるものではない
//   (シーケンスを起動しないので ADD_SB_EMPTY が出る)。
// -----------------------------------------------------------------------------
class addcore_base_test extends uvm_test;
  `uvm_component_utils(addcore_base_test)

  addcore_env env;
  env_config  cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void configure();
  endfunction

  function void build_phase(uvm_phase phase);
    int n;
    super.build_phase(phase);
    cfg = env_config::type_id::create("cfg");
    cfg.is_active      = UVM_ACTIVE;
    cfg.has_scoreboard = 1'b1;
    cfg.has_coverage   = 1'b0;      // 加算器単体に対応する covergroup は無い
    if (!uvm_config_db#(virtual addcore_if)::get(this, "", "addcore_vif", cfg.addcore_vif))
      `uvm_fatal("ADD_TEST", "addcore_vif not set in uvm_config_db")
    if ($value$plusargs("N_ITEM=%d", n)) cfg.num_blocks = n;
    configure();
    uvm_config_db#(env_config)::set(this, "env", "cfg", cfg);
    env = addcore_env::type_id::create("env", this);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    uvm_phase run_ph;
    run_ph = uvm_run_phase::get();
    run_ph.phase_done.set_drain_time(this, 2 * cfg.clk_period);
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
// mxfp4_r2f_test (R2f)
//   directed (A1 反例・完全相殺・タイ点) のあとランダムを流す。
// -----------------------------------------------------------------------------
class mxfp4_r2f_test extends addcore_base_test;
  `uvm_component_utils(mxfp4_r2f_test)

  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  task run_phase(uvm_phase phase);
    r2f_directed_seq d_seq;
    r2f_rand_seq     r_seq;
    phase.raise_objection(this);
    d_seq = r2f_directed_seq::type_id::create("d_seq");
    d_seq.start(env.add_agt.add_sequencer);
    r_seq = r2f_rand_seq::type_id::create("r_seq");
    r_seq.n_pairs = cfg.num_blocks;
    r_seq.start(env.add_agt.add_sequencer);
    phase.drop_objection(this);
  endtask
endclass

// -----------------------------------------------------------------------------
// mxfp4_r2f_directed_test
//   directed だけ。境界ケースの回帰を短時間で回したいとき用。
//   指数差の帯を踏まない可能性があるので非 vacuous 性チェックは外す。
// -----------------------------------------------------------------------------
class mxfp4_r2f_directed_test extends addcore_base_test;
  `uvm_component_utils(mxfp4_r2f_directed_test)

  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  function void configure();
    cfg.check_b2b = 1'b0;
  endfunction

  task run_phase(uvm_phase phase);
    r2f_directed_seq d_seq;
    phase.raise_objection(this);
    d_seq = r2f_directed_seq::type_id::create("d_seq");
    d_seq.start(env.add_agt.add_sequencer);
    phase.drop_objection(this);
  endtask
endclass
