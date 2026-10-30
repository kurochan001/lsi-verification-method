// -----------------------------------------------------------------------------
// gemm_test_lib
//   GEMM レベルの uvm_test (付録A A.9、シナリオ E3)。トップは hw_gemm_top。
//
//     make sim-uvm-gemm UVM_TEST=mxfp4_e3_test
//
//   drain time は 1 + KBLK + LAT のあと C を読み切るまで。余裕を見て
//   (KBLK + LAT + 8) x 周期 とする。
//
//   `gemm_base_test` は基底で、単体で走らせるものではない
//   (シーケンスを起動しないので GEMM_SB_EMPTY が出る)。
// -----------------------------------------------------------------------------
class gemm_base_test extends uvm_test;
  `uvm_component_utils(gemm_base_test)

  gemm_env   env;
  env_config cfg;

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
    cfg.has_coverage   = 1'b0;   // GEMM レベルの covergroup は 9.4 節に無い
    if (!uvm_config_db#(virtual gemm_if)::get(this, "", "gemm_vif", cfg.gemm_vif))
      `uvm_fatal("GEMM_TEST", "gemm_vif not set in uvm_config_db")
    if ($value$plusargs("N_ITEM=%d", n)) cfg.num_blocks = n;
    configure();
    uvm_config_db#(env_config)::set(this, "env", "cfg", cfg);
    env = gemm_env::type_id::create("env", this);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    uvm_phase run_ph;
    run_ph = uvm_run_phase::get();
    run_ph.phase_done.set_drain_time(this, (4 + mxfp4_pkg::LAT + 8) * cfg.clk_period);
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
// mxfp4_e3_identity_test : 単位行列 x 任意行列 (E3 の中核)
// -----------------------------------------------------------------------------
class mxfp4_e3_identity_test extends gemm_base_test;
  `uvm_component_utils(mxfp4_e3_identity_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  task run_phase(uvm_phase phase);
    e3_identity_seq seq;
    phase.raise_objection(this);
    seq = e3_identity_seq::type_id::create("seq");
    seq.start(env.gemm_agt.gemm_sequencer);
    phase.drop_objection(this);
  endtask
endclass

// -----------------------------------------------------------------------------
// mxfp4_e3_test : E3 一式 (単位行列 + ランダム + NaN 伝播)
// -----------------------------------------------------------------------------
class mxfp4_e3_test extends gemm_base_test;
  `uvm_component_utils(mxfp4_e3_test)
  function new(string name, uvm_component parent); super.new(name, parent); endfunction

  // **既定のランダム実行数は 1 にする** (単位行列 + ランダム 1 + NaN = 計 3 実行)。
  // GEMM は DUT が 16 PE ぶんあり、4-state の sukimasim では 1 回の実行
  // (0.69 us) に **CPU 1200 秒**かかる (組合せ整定予算を上げた状態で)。
  // 3 実行でおよそ 1 時間。これ以上は現実的でない。
  // 量を稼ぐのはプレーン SV 版 (`make sim-gemm N_GEMM=500`、Verilator で
  // 8,553 チェック) の役目で、こちらは X 伝播・done サイクル規約・
  // NaN 伝播の確認に絞る。
  // **N_ITEM を明示したときはその値を使う** (未指定のときだけ 1 へ)。
  function void configure();
    int n;
    if (!$value$plusargs("N_ITEM=%d", n)) cfg.num_blocks = 1;
  endfunction

  task run_phase(uvm_phase phase);
    e3_identity_seq i_seq;
    e3_rand_seq     r_seq;
    e3_nan_seq      n_seq;
    phase.raise_objection(this);
    i_seq = e3_identity_seq::type_id::create("i_seq");
    i_seq.start(env.gemm_agt.gemm_sequencer);
    r_seq = e3_rand_seq::type_id::create("r_seq");
    r_seq.n_runs = cfg.num_blocks;
    r_seq.start(env.gemm_agt.gemm_sequencer);
    n_seq = e3_nan_seq::type_id::create("n_seq");
    n_seq.start(env.gemm_agt.gemm_sequencer);
    phase.drop_objection(this);
  endtask
endclass
