// -----------------------------------------------------------------------------
// gemm_env (付録A A.9)
//   gemm_agent + gemm_scoreboard、それに**空の virtual_sequencer**。
//
//   [A.9.1 に従って空の virtual_sequencer を最初から置く]
//     付録A は「初期は方式 Y (専用 gemm driver) で立ち上げ、複数エージェント
//     協調が必要になった段階で方式 X (virtual sequence) へ移行する。将来拡張の
//     痛点を減らすため、空の virtual_sequencer は最初から配置しておく」と
//     している。本実装は方式 Y だが、その助言どおり器だけ用意してある。
//     いま使う側は無く、gemm_sequencer への参照を持たせてあるだけ。
//     bdp_agent を passive で載せて協調させる段になったら、ここへ
//     他の sequencer のハンドルを足して virtual sequence から叩く。
// -----------------------------------------------------------------------------

// 空の virtual sequencer (A.9.1)
class mxfp4_virtual_sequencer extends uvm_sequencer;
  `uvm_component_utils(mxfp4_virtual_sequencer)

  // 方式 X へ移行するとき、ここへ各 agent の sequencer を繋ぐ。
  uvm_sequencer #(gemm_item) gemm_sqr;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
endclass

class gemm_env extends uvm_env;
  `uvm_component_utils(gemm_env)

  env_config              cfg;
  gemm_agent              gemm_agt;
  gemm_scoreboard         sb;
  mxfp4_virtual_sequencer v_sqr;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("GEMM_ENV", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    gemm_agt = gemm_agent::type_id::create("gemm_agt", this);
    if (cfg.has_scoreboard)
      sb = gemm_scoreboard::type_id::create("sb", this);
    if (cfg.is_active == UVM_ACTIVE)
      v_sqr = mxfp4_virtual_sequencer::type_id::create("v_sqr", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.has_scoreboard) begin
      gemm_agt.mon.ap_in .connect(sb.sub_in .analysis_export);
      gemm_agt.mon.ap_out.connect(sb.sub_out.analysis_export);
    end
    if (cfg.is_active == UVM_ACTIVE)
      v_sqr.gemm_sqr = gemm_agt.gemm_sequencer;
  endfunction
endclass
