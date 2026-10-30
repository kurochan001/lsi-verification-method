// -----------------------------------------------------------------------------
// enc_env (付録A A.8.2 を quant_encoder レベルへ適用したもの)
//   enc_agent + enc_scoreboard + cg_enc の subscriber。
//
//   BDP 版 mxfp4_env との違いは、B2 (acc RAW ハザード) の連続投入チェックが
//   無いこと。累積器を持たないエンコーダには該当する論点がない
//   (enc_agent.svh の冒頭を参照)。
//
//   段別カバレッジ (cg_enc、A.7.2) は monitor の ap_stg から取る。
//   quant_valid_dbg のサイクルの e_rel / mag3 / tie_hit を 32 レーン分
//   まとめて 1 トランザクションにし、cov_enc が foreach で sample() する。
// -----------------------------------------------------------------------------
class enc_env extends uvm_env;
  `uvm_component_utils(enc_env)

  env_config     cfg;
  enc_agent      enc_agt;
  enc_scoreboard sb;
  cov_enc        cov;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ENC_ENV", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    enc_agt = enc_agent::type_id::create("enc_agt", this);
    if (cfg.has_scoreboard)
      sb = enc_scoreboard::type_id::create("sb", this);
    if (cfg.has_coverage)
      cov = cov_enc::type_id::create("cov", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.has_scoreboard) begin
      enc_agt.mon.ap_in .connect(sb.sub_in .analysis_export);
      enc_agt.mon.ap_out.connect(sb.sub_out.analysis_export);
    end
    if (cfg.has_coverage)
      enc_agt.mon.ap_stg.connect(cov.analysis_export);
  endfunction

  function void check_phase(uvm_phase phase);
    if (cfg.check_coverage && cfg.has_coverage) begin
      `uvm_info("ENC_ENV_COV", $sformatf("cg_enc=%0.2f%% (%0d samples)",
                cov.coverage(), cov.n_sample), UVM_LOW)
      if (cov.coverage() < 100.0)
        `uvm_error("ENC_ENV_COV", "cg_enc below 100%")
    end
  endfunction
endclass
