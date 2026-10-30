// -----------------------------------------------------------------------------
// bdp_agent 一式 (付録A A.5)
//   driver / monitor / sequencer / agent。
//
//   [付録A A.5.1 からの変更 — 隙間なし連続投入]
//     A.5.1 の骨格は item ごとに in_valid を落とし、さらに
//     do @(vif.cb); while (in_ready !== 1) が in_ready = 1 でも 1 サイクル
//     消費するため、最短でも 1 item = 2 サイクルになる。本文が要求する
//     「隙間なく連続投入」(B2 の RAW ハザード検出に必須) を満たさない
//     (docs/spec_review_appendixA.md A-1)。
//
//     本実装は 1 プロセスで連続投入を成立させる。要点は 2 つ。
//       (a) 毎 negedge に try_next_item() でノンブロッキングに item を取る。
//           item があれば in_valid を落とさずに次のデータへ直結し、
//           無ければその周期だけ in_valid を落とす。
//       (b) item_done() を次の negedge より前に呼ぶ。シーケンスは半周期のうちに
//           次の item を sequencer へ渡せるので、次の negedge の
//           try_next_item() が成功し、隙間なく連続投入になる。
//
//     連続投入が実際に起きたことは monitor が n_b2b で観測し、
//     check_phase で 1 回以上を要求する (要求を形骸化させないため)。
//
//   [付録A A.3.1 / A.5.1 からの変更 — negedge 駆動 + ブロッキング代入]
//     A.5.1 は clocking block (cb) 経由の駆動を前提にしているが、sukimasim では
//     clocking block イベントが使えない (下記)。素の信号を posedge で NBA 駆動
//     する形も試したが、初期化と最初の投入が同一時刻に重なると同一変数への
//     NBA が同時刻に 2 回積まれ、どちらが残るかで結果が変わってしまう。
//     プレーン SV 版 tb_top と同じく negedge でブロッキング駆動すれば、
//     駆動時刻と DUT のサンプル時刻 (posedge) が構造的に分離され、
//     モニタの posedge サンプルとも競合しない。
//
//   [付録A A.3.1 からの変更 — clocking block を使わない]
//     A.3.1 は driver / monitor を clocking block (cb) 経由にすると規定して
//     いるが、sukimasim 0.9.9.2 では clocking block イベント @(vif.cb) の
//     待ちが、同じクロックを待つ他のプロセス (別の clocking block や
//     virtual interface 経由の @(posedge vif.clk)) と共存すると最初の 1 回
//     しかトリガされない (Issue #1171)。driver も monitor も 1 サイクルで
//     止まり、モニタが何も観測しなくなる。
//     そこで素の信号をノンブロッキング代入で駆動し、@(posedge vif.clk) で
//     サンプルする方式にした。駆動が NBA なので posedge 時点の値は DUT の
//     always_ff が見る値と一致し、clocking block と同じサンプル意味論になる
//     (プレーン SV 版 tb_top と同じ方式)。
//     インターフェース側の cb / cb_mon 定義は付録A 準拠の記録として残してある。
// -----------------------------------------------------------------------------

class bdp_driver extends uvm_driver #(blk_pair_item);
  `uvm_component_utils(bdp_driver)

  virtual bdp_if vif;
  env_config     cfg;
  int unsigned   n_sent;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("DRV", "env_config not set")
    vif = cfg.bdp_vif;
    if (vif == null) `uvm_fatal("DRV", "bdp_vif is null")
    n_sent = 0;
  endfunction

  task run_phase(uvm_phase phase);
    blk_pair_item tr;
    // リセットが掛かってから解除されるまで待つ (hw_top は非同期リセットの
    // negedge を確実に作るため rst_n を 1 -> 0 -> 1 と動かす)
    wait (vif.rst_n === 1'b0);
    wait (vif.rst_n === 1'b1);
    @(negedge vif.clk);
    vif.in_valid <= 1'b0;
    vif.first    <= 1'b0;
    vif.last     <= 1'b0;
    vif.a_block  <= '0;
    vif.b_block  <= '0;
    forever begin
      @(negedge vif.clk);
      // ストール中 (in_ready = 0) は valid とデータを保持する (3.3 節)
      if (vif.in_ready !== 1'b1) continue;
      seq_item_port.try_next_item(tr);
      if (tr == null) begin
        vif.in_valid <= 1'b0;         // 次 item がまだ無い
      end else begin
        vif.in_valid <= 1'b1;
        vif.a_block  <= tr.a_block;
        vif.b_block  <= tr.b_block;
        vif.first    <= tr.first;
        vif.last     <= tr.last;
        seq_item_port.item_done();    // 次の negedge までにシーケンスが先行できる
        n_sent++;
      end
    end
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("DRV", $sformatf("driven %0d item(s)", n_sent), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// bdp_monitor (A.5.2)
//   入力側 / 出力側 / 段別 dbg の 4 系統 analysis port。
// -----------------------------------------------------------------------------
class bdp_monitor extends uvm_monitor;
  `uvm_component_utils(bdp_monitor)

  virtual bdp_if vif;
  env_config     cfg;

  uvm_analysis_port #(bdp_in_item)     ap_in;
  uvm_analysis_port #(bdp_result_item) ap_out;
  uvm_analysis_port #(bdp_dbg_item)    ap_sop;
  uvm_analysis_port #(bdp_dbg_item)    ap_exp;

  int unsigned n_in, n_out, n_sop, n_exp;
  // 直前サイクルに続けて転送が起きた回数 (A-1 の裏付け)
  int unsigned n_b2b;
  // 直前サイクルに転送が起きたか (sample_in の状態)
  protected bit prev_accept;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap_in  = new("ap_in",  this);
    ap_out = new("ap_out", this);
    ap_sop = new("ap_sop", this);
    ap_exp = new("ap_exp", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("MON", "env_config not set")
    vif = cfg.bdp_vif;
    if (vif == null) `uvm_fatal("MON", "bdp_vif is null")
    n_in = 0; n_out = 0; n_sop = 0; n_exp = 0; n_b2b = 0;
  endfunction

  // 付録A A.5.2 は fork mon_in(); mon_out(); mon_sop(); mon_exp(); join で
  // 4 プロセスに分けているが、そう書くと sukimasim Issue #1171 を踏む
  // (同じクロックを待つプロセスが増えるほど clocking block / イベント待ちの
  //  取りこぼしが起きやすく、モニタが何も観測しなくなる)。
  // 段分離 (A.5.2 / A.7.3) の要点は analysis port とトランザクションを段ごとに
  // 分けることであって、プロセスを分けることではない。1 プロセスで 4 系統を
  // サンプルしても段分離は保たれる。
  task run_phase(uvm_phase phase);
    prev_accept = 1'b0;
    forever begin
      @(posedge vif.clk);
      // posedge の直後 (RTL のノンブロッキング更新後) に読む。
      // sukimasim 0.9.9.2 では @(posedge) 直後の Active 領域で読むと、
      // 観測ポートによって更新前 / 更新後が混ざり sop4_dbg が X になる。
      // driver は negedge 駆動なので、ここで少し待っても競合しない。
      #1;
      if (vif.rst_n !== 1'b1) begin
        prev_accept = 1'b0;
      end else begin
        sample_in();
        sample_out();
        sample_sop();
        sample_exp();
      end
    end
  endtask

  // 入力側 (in_valid && in_ready 契機)
  task sample_in();
    bdp_in_item tr;
    if (vif.in_valid === 1'b1 && vif.in_ready === 1'b1) begin
      tr = bdp_in_item::type_id::create("mon_in");
      tr.a_block = vif.a_block;
      tr.b_block = vif.b_block;
      tr.first   = vif.first;
      tr.last    = vif.last;
      `uvm_info("MON_IN", $sformatf("a=%034h b=%034h first=%0b last=%0b",
                tr.a_block, tr.b_block, tr.first, tr.last), UVM_HIGH)
      ap_in.write(tr);
      n_in++;
      if (prev_accept) n_b2b++;
      prev_accept = 1'b1;
    end else begin
      prev_accept = 1'b0;
    end
  endtask

  // 出力側 (out_valid && out_ready 契機)
  task sample_out();
    bdp_result_item tr;
    if (vif.out_valid === 1'b1 && vif.out_ready === 1'b1) begin
      tr = bdp_result_item::type_id::create("mon_out");
      tr.result = vif.result;
      ap_out.write(tr);
      n_out++;
    end
  endtask

  // SoP4 段 (sop_valid_dbg 契機)
  task sample_sop();
    bdp_dbg_item tr;
    if (vif.sop_valid_dbg === 1'b1) begin
      tr = bdp_dbg_item::type_id::create("mon_sop");
      tr.sop4 = vif.sop4_dbg;
      `uvm_info("MON_SOP", $sformatf("sop4=%0d", tr.sop4), UVM_HIGH)
      ap_sop.write(tr);
      n_sop++;
    end
  endtask

  // 指数段 (exp_valid_dbg 契機)
  task sample_exp();
    bdp_dbg_item tr;
    if (vif.exp_valid_dbg === 1'b1) begin
      tr = bdp_dbg_item::type_id::create("mon_exp");
      tr.exp_internal = vif.exp_internal_dbg;
      ap_exp.write(tr);
      n_exp++;
    end
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("MON", $sformatf("in=%0d out=%0d sop=%0d exp=%0d back-to-back=%0d",
                               n_in, n_out, n_sop, n_exp, n_b2b), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// bdp_agent (A.5.3)
//   is_active == UVM_ACTIVE のとき driver / sequencer を生成し、
//   UVM_PASSIVE のとき monitor のみ生成する (GEMM レベルでの passive 再利用)。
// -----------------------------------------------------------------------------
class bdp_agent extends uvm_agent;
  `uvm_component_utils(bdp_agent)

  env_config                       cfg;
  bdp_driver                       drv;
  uvm_sequencer #(blk_pair_item)   bdp_sequencer;
  bdp_monitor                      mon;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("AGT", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    mon = bdp_monitor::type_id::create("mon", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      drv           = bdp_driver::type_id::create("drv", this);
      bdp_sequencer = uvm_sequencer #(blk_pair_item)::type_id::create("bdp_sequencer", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.is_active == UVM_ACTIVE)
      drv.seq_item_port.connect(bdp_sequencer.seq_item_export);
  endfunction
endclass
