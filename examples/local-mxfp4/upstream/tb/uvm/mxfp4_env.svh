// -----------------------------------------------------------------------------
// mxfp4_env (付録A A.8.2)
//   BDP 単体レベルの env。bdp_agent + scoreboard + 段別カバレッジ subscriber。
//
//   [付録A A.8.2 への追加]
//     骨格は ap_in / ap_out を scoreboard へ繋ぐところまで。本実装では
//     ap_sop を scoreboard の SoP4 照合 (R1 の合否基準) と cov_bdp_sop へ、
//     ap_exp を cov_bdp_exp へ配線する (図13 の TLM 配線に対応)。
// -----------------------------------------------------------------------------
class mxfp4_env extends uvm_env;
  `uvm_component_utils(mxfp4_env)

  env_config       cfg;
  bdp_agent        bdp_agt;
  mxfp4_scoreboard sb;
  cov_bdp_in       cov_in;
  cov_bdp_sop      cov_sop;
  cov_bdp_exp      cov_exp;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ENV", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    bdp_agt = bdp_agent::type_id::create("bdp_agt", this);
    if (cfg.has_scoreboard)
      sb = mxfp4_scoreboard::type_id::create("sb", this);
    if (cfg.has_coverage) begin
      cov_in  = cov_bdp_in ::type_id::create("cov_in",  this);
      cov_sop = cov_bdp_sop::type_id::create("cov_sop", this);
      cov_exp = cov_bdp_exp::type_id::create("cov_exp", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.has_scoreboard) begin
      bdp_agt.mon.ap_in .connect(sb.sub_in .analysis_export);
      bdp_agt.mon.ap_out.connect(sb.sub_out.analysis_export);
      bdp_agt.mon.ap_sop.connect(sb.sub_sop.analysis_export);
    end
    if (cfg.has_coverage) begin
      bdp_agt.mon.ap_in .connect(cov_in .analysis_export);
      bdp_agt.mon.ap_sop.connect(cov_sop.analysis_export);
      bdp_agt.mon.ap_exp.connect(cov_exp.analysis_export);
    end
  endfunction

  function void check_phase(uvm_phase phase);
    // 隙間なし連続投入が実際に起きたか (A-1: これが無いと B2 の RAW ハザードを
    // 検出できず、回帰が緑のまま通ってしまう)
    if (cfg.check_b2b && cfg.is_active == UVM_ACTIVE && bdp_agt.mon.n_b2b == 0)
      `uvm_error("ENV_B2B",
        "no back-to-back transfer observed: the driver leaves gaps and B2 (acc RAW hazard) cannot be detected")

    if (cfg.check_coverage && cfg.has_coverage) begin
      `uvm_info("ENV_COV", $sformatf("cg_bdp_in=%0.2f%% cg_bdp_sop=%0.2f%% cg_bdp_exp=%0.2f%%",
                cov_in.coverage(), cov_sop.coverage(), cov_exp.coverage()), UVM_LOW)
      if (cov_in.coverage() < 100.0 || cov_sop.coverage() < 100.0 ||
          cov_exp.coverage() < 100.0)
        `uvm_error("ENV_COV", "functional coverage below 100%")
    end
  endfunction
endclass
