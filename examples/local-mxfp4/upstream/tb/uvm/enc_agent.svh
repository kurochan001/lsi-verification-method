// -----------------------------------------------------------------------------
// enc_agent 一式 (付録A A.5 を quant_encoder レベルへ適用したもの)
//   driver / monitor / sequencer / agent。
//
//   BDP 版 (bdp_agent.svh) からの違いは 3 点で、いずれもエンコーダの
//   インターフェースが BDP と違うことによる。
//
//   1. **ready が無い。** quant_encoder は in_valid だけで受理し、
//      バックプレッシャを持たない (仕様書 7 章)。したがって in_ready 待ちも
//      「隙間なし連続投入」の n_b2b カウントも無い。B2 の RAW ハザードは
//      累積器を持つ BDP 固有の論点なので、こちらでは検査しない。
//
//   2. **駆動はブロッキング代入。** 駆動対象 v_arr は unpacked 配列で、
//      sukimasim 0.9.9.2 では interface の unpacked 配列要素への NBA が
//      落ちる条件がある (Issue #1320)。negedge でブロッキング駆動すれば
//      駆動時刻と DUT のサンプル時刻 (posedge) は構造的に分離されるので、
//      NBA と意味論は変わらない (プレーン SV 版 tb_quant_encoder と同じ形)。
//
//   3. **観測は 2 契機。** quant_valid_dbg のサイクルで段別の観測ポート
//      (e_rel / mag3 / tie) を、out_valid のサイクルで blk_o を採る。
//      quant_valid_dbg は blk_o を載せる段レジスタの 1 つ手前なので、
//      同じ投入に対して quant_valid_dbg が out_valid の 1 サイクル前に立つ
//      (仕様書 7.6 節)。
//
//   clocking block は使わない (Issue #1171。bdp_agent.svh と同じ理由)。
//   monitor も 1 プロセスで両契機をサンプルする (指摘 A-9)。
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
// packed <-> unpacked のヘルパ (パッケージスコープの関数)
//
//   **クラスのメソッド内で書いてはいけない。** sukimasim 0.9.9.2 では
//   クラスのタスク / 関数の中で `flat[W*i +: W]` のようにループ変数を
//   部分選択のオフセットに使うと、i が 1'bx として評価されて代入が落ちる
//   (`Assignment failed: Packed array index must be an integer: index=i`)。
//   streaming (`{>>{arr}} = flat`) も同じ文脈では効かない。
//   パッケージスコープの automatic function なら正しく動く
//   (mxfp4_ref_pkg が同じ書き方で動いているのと同じ)。
//
//   詰め方は driver の {>>{tr.v}} と揃える (要素 0 が最上位側)。
// -----------------------------------------------------------------------------
function automatic void enc_unflatten_v(input logic [32*K-1:0] flat,
                                        output bit [31:0] v [K]);
  for (int i = 0; i < K; i++) v[i] = flat[32*(K-1-i) +: 32];
endfunction

function automatic void enc_unflatten_stage(
    input  logic [SCALED_EXP_W*K-1:0] e_flat,
    input  logic [3*K-1:0]            m_flat,
    input  logic [K-1:0]              t_flat,
    output bit signed [SCALED_EXP_W-1:0] e [K],
    output bit [2:0]                     m [K],
    output bit                           t [K]);
  for (int i = 0; i < K; i++) begin
    e[i] = e_flat[SCALED_EXP_W*i +: SCALED_EXP_W];
    m[i] = m_flat[3*i +: 3];
    t[i] = t_flat[i];
  end
endfunction

class enc_driver extends uvm_driver #(enc_item);
  `uvm_component_utils(enc_driver)

  virtual enc_if vif;
  env_config     cfg;
  int unsigned   n_sent;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ENC_DRV", "env_config not set")
    vif = cfg.enc_vif;
    if (vif == null) `uvm_fatal("ENC_DRV", "enc_vif is null")
    n_sent = 0;
  endfunction

  task run_phase(uvm_phase phase);
    enc_item tr;
    wait (vif.rst_n === 1'b0);
    wait (vif.rst_n === 1'b1);
    @(negedge vif.clk);
    vif.in_valid = 1'b0;
    forever begin
      @(negedge vif.clk);
      seq_item_port.try_next_item(tr);
      if (tr == null) begin
        vif.in_valid = 1'b0;               // 次 item がまだ無い
      end else begin
        // enc_if は packed ベクタしか持たない (Issue #1320 の回避)。
        // **部分選択の書き込みは使わない。** sukimasim 0.9.9.2 では
        // クラスのタスク内のローカル変数への `loc[32*i +: 32] = x` が
        // 無言で落ち、変数が X のまま DUT へ流れる (詰まった実例)。
        // streaming 演算子なら 1 文で詰められる。要素 0 が最上位側に入るので、
        // 展開側 (hw_enc_top / monitor) もその順で読む。
        vif.v_flat = {>>{tr.v}};
        vif.in_valid = 1'b1;
        seq_item_port.item_done();         // 次の negedge までにシーケンスが先行できる
        n_sent++;
      end
    end
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("ENC_DRV", $sformatf("driven %0d block(s)", n_sent), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// enc_monitor
//   ap_in  : 投入されたブロック (in_valid 契機)
//   ap_out : blk_o (out_valid 契機)
//   ap_stg : 段別の観測ポート (quant_valid_dbg 契機。cg_enc 用)
// -----------------------------------------------------------------------------
class enc_monitor extends uvm_monitor;
  `uvm_component_utils(enc_monitor)

  virtual enc_if vif;
  env_config     cfg;

  uvm_analysis_port #(enc_item)        ap_in;
  uvm_analysis_port #(enc_result_item) ap_out;
  uvm_analysis_port #(enc_result_item) ap_stg;

  int unsigned n_in, n_out, n_stg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap_in  = new("ap_in",  this);
    ap_out = new("ap_out", this);
    ap_stg = new("ap_stg", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ENC_MON", "env_config not set")
    vif = cfg.enc_vif;
    if (vif == null) `uvm_fatal("ENC_MON", "enc_vif is null")
    n_in = 0; n_out = 0; n_stg = 0;
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      @(posedge vif.clk);
      // posedge の直後 (RTL のノンブロッキング更新後) に読む。
      // driver は negedge 駆動なので、ここで待っても競合しない
      // (bdp_monitor と同じ理由)。
      #1;
      if (vif.rst_n === 1'b1) begin
        sample_in();
        sample_stage();
        sample_out();
      end
    end
  endtask

  // 投入側 (in_valid 契機。ready が無いので valid だけで受理される)
  task sample_in();
    enc_item tr;
    // enc_item.v は bit 型なので、こちらも bit で宣言する。
    // logic の unpacked 配列を bit の unpacked 配列へ代入すると
    // 要素型が等価でなく (IEEE 1800-2023 §7.4.2)、代入が成立しない。
    bit [31:0] v_loc [K];
    if (vif.in_valid === 1'b1) begin
      tr = enc_item::type_id::create("mon_in");
      enc_unflatten_v(vif.v_flat, v_loc);
      tr.v = v_loc;
      ap_in.write(tr);
      n_in++;
    end
  endtask

  // 段別の観測ポート (quant_valid_dbg 契機。仕様書 7.6 節)
  task sample_stage();
    enc_result_item tr;
    bit signed [SCALED_EXP_W-1:0] e_loc [K];
    bit [2:0]                     m_loc [K];
    bit                           t_loc [K];
    `uvm_info("DBG_TOP", $sformatf("entered, qv=%b", vif.quant_valid_dbg), UVM_LOW)
    if (vif.quant_valid_dbg === 1'b1) begin
      `uvm_info("DBG_IN", "inside the if", UVM_LOW)
      tr = enc_result_item::type_id::create("mon_stg");
      enc_unflatten_stage(vif.e_rel_flat, vif.mag3_flat, vif.tie_flat,
                          e_loc, m_loc, t_loc);
      tr.e_rel = e_loc;
      tr.mag3  = m_loc;
      tr.tie   = t_loc;
      `uvm_info("DBG_PRE", $sformatf("about to write, mag3[0]=%0d e_rel[0]=%0d",
                m_loc[0], e_loc[0]), UVM_LOW)
      ap_stg.write(tr);
      n_stg++;
    end
  endtask

  // 出力側 (out_valid 契機)
  task sample_out();
    enc_result_item tr;
    if (vif.out_valid === 1'b1) begin
      tr = enc_result_item::type_id::create("mon_out");
      tr.blk = vif.blk_o;
      `uvm_info("ENC_MON_OUT", $sformatf("blk=%034h", tr.blk), UVM_HIGH)
      ap_out.write(tr);
      n_out++;
    end
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("ENC_MON", $sformatf("in=%0d stage=%0d out=%0d", n_in, n_stg, n_out), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// enc_agent (A.5.3)
// -----------------------------------------------------------------------------
class enc_agent extends uvm_agent;
  `uvm_component_utils(enc_agent)

  env_config                  cfg;
  enc_driver                  drv;
  uvm_sequencer #(enc_item)   enc_sequencer;
  enc_monitor                 mon;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ENC_AGT", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    mon = enc_monitor::type_id::create("mon", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      drv           = enc_driver::type_id::create("drv", this);
      enc_sequencer = uvm_sequencer #(enc_item)::type_id::create("enc_sequencer", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.is_active == UVM_ACTIVE)
      drv.seq_item_port.connect(enc_sequencer.seq_item_export);
  endfunction
endclass
