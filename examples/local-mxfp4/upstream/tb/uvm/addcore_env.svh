// -----------------------------------------------------------------------------
// addcore_env (付録A A.10)
//   addcore_agent + addcore_scoreboard。
//
//   段別カバレッジ subscriber は置かない。仕様書 9.4 節の covergroup は
//   BDP と エンコーダに対して定義されており、加算器単体には対応する
//   covergroup が無い (R2f の網羅性は指数差の帯と完全相殺の件数で見る。
//   addcore_scoreboard の report_phase を参照)。
// -----------------------------------------------------------------------------
class addcore_env extends uvm_env;
  `uvm_component_utils(addcore_env)

  env_config         cfg;
  addcore_agent      add_agt;
  addcore_scoreboard sb;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ADD_ENV", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    add_agt = addcore_agent::type_id::create("add_agt", this);
    if (cfg.has_scoreboard)
      sb = addcore_scoreboard::type_id::create("sb", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.has_scoreboard)
      add_agt.mon.ap.connect(sb.sub.analysis_export);
  endfunction
endclass
