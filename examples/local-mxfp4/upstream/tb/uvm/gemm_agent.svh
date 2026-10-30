// -----------------------------------------------------------------------------
// gemm_agent 一式 (付録A A.9、方式 Y = 専用 gemm driver)
//   mxfp4_gemm_top 用の driver / monitor / sequencer / agent。
//
//   付録A A.9.1 は「初期は方式 Y で立ち上げ、複数エージェント協調が必要に
//   なった段階で方式 X (virtual sequencer / virtual sequence) へ移行する。
//   将来の痛点を減らすため空の virtual_sequencer は最初から置く」としており、
//   本実装はそれに従う (空の virtual sequencer は gemm_env.svh にある)。
//
//   driver は 1 item = 1 回の GEMM 実行として扱う:
//     A 側 ROWS x KBLK -> B 側 COLS x KBLK をロード -> start を 1 サイクル ->
//     done を待つ。次の item は done の後から始まる。
//
//   monitor は start から done までのサイクル数を数え (A.9.2)、done の次の
//   サイクルで C を読む (8.6 節の「c_mat は done の次サイクル以降に読み出し、
//   次の start まで保持される」規約)。
//
//   **Issue #1322 を踏まないこと。** UVM コンポーネントのタスクで
//   `if (...) begin ... for ... ; <handle>.method(); end` と書くと、
//   ループがローカルへ書いた値が失われる。ループを伴う取り出しは
//   下のパッケージスコープ関数へ切り出してある。
// -----------------------------------------------------------------------------

// 観測したバッファを item へ写す (ループを伴うのでパッケージスコープに置く。
// クラスのメソッド内に置くと Issue #1322 の条件を作りやすい)
function automatic void gemm_copy_bufs(input bit [BLOCK_W-1:0] a [4][4],
                                       input bit [BLOCK_W-1:0] b [4][4],
                                       gemm_item tr);
  for (int r = 0; r < 4; r++)
    for (int k = 0; k < 4; k++) begin
      tr.a_mat[r][k] = a[r][k];
      tr.b_mat[r][k] = b[r][k];
    end
endfunction

class gemm_driver extends uvm_driver #(gemm_item);
  `uvm_component_utils(gemm_driver)

  virtual gemm_if vif;
  env_config      cfg;
  int unsigned    n_sent;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("GEMM_DRV", "env_config not set")
    vif = cfg.gemm_vif;
    if (vif == null) `uvm_fatal("GEMM_DRV", "gemm_vif is null")
    n_sent = 0;
  endfunction

  task run_phase(uvm_phase phase);
    gemm_item tr;
    wait (vif.rst_n === 1'b0);
    wait (vif.rst_n === 1'b1);
    @(negedge vif.clk);
    vif.wr_en = 1'b0;
    vif.start = 1'b0;
    forever begin
      seq_item_port.get_next_item(tr);
      load_a(tr);
      load_b(tr);
      pulse_start();
      wait_done();
      seq_item_port.item_done();
      n_sent++;
    end
  endtask

  // A 側バッファ: addr = r * KBLK + k
  task load_a(gemm_item tr);
    @(negedge vif.clk);
    for (int r = 0; r < int'(tr.rows); r++) begin
      for (int k = 0; k < int'(tr.kblk); k++) begin
        vif.wr_en   = 1'b1;
        vif.wr_sel  = 1'b0;
        vif.wr_addr = 4'(r * int'(tr.kblk) + k);
        vif.wr_data = tr.a_mat[r][k];
        @(negedge vif.clk);
      end
    end
    vif.wr_en = 1'b0;
  endtask

  // B 側バッファ: addr = c * KBLK + k
  task load_b(gemm_item tr);
    for (int c = 0; c < int'(tr.cols); c++) begin
      for (int k = 0; k < int'(tr.kblk); k++) begin
        vif.wr_en   = 1'b1;
        vif.wr_sel  = 1'b1;
        vif.wr_addr = 4'(c * int'(tr.kblk) + k);
        vif.wr_data = tr.b_mat[c][k];
        @(negedge vif.clk);
      end
    end
    vif.wr_en = 1'b0;
  endtask

  // start を 1 サイクルだけ立てる
  task pulse_start();
    @(negedge vif.clk);
    vif.start = 1'b1;
    @(negedge vif.clk);
    vif.start = 1'b0;
  endtask

  // done を待つ (次の item のロードが走り出さないように driver 側でも待つ)
  task wait_done();
    int guard;
    guard = 0;
    forever begin
      @(posedge vif.clk);
      #1;
      guard++;
      if (vif.done === 1'b1) break;
      if (guard > 500) begin
        `uvm_error("GEMM_DRV", "timeout waiting for done")
        break;
      end
    end
    // C は done のサイクル末にラッチされる。monitor が読み終えるまで 1 サイクル置く。
    @(negedge vif.clk);
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("GEMM_DRV", $sformatf("driven %0d GEMM run(s)", n_sent), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// gemm_monitor (A.9.2)
//   ap_in  : 投入された A / B (driver が書いたバッファを再構成せず、
//            wr_en の観測から積み上げる)
//   ap_out : 1 回の実行の結果 C と done サイクル数
// -----------------------------------------------------------------------------
class gemm_monitor extends uvm_monitor;
  `uvm_component_utils(gemm_monitor)

  virtual gemm_if vif;
  env_config      cfg;

  uvm_analysis_port #(gemm_item)        ap_in;
  uvm_analysis_port #(gemm_result_item) ap_out;

  int unsigned n_in, n_out;
  // 8.6 節の保持規約 (done の後、次の start まで C が変わらないこと) の違反数
  int unsigned n_hold_viol;

  // 観測中のバッファ (driver が書いた順を そのまま拾う)
  protected bit [BLOCK_W-1:0] obs_a [4][4];
  protected bit [BLOCK_W-1:0] obs_b [4][4];

  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap_in  = new("ap_in",  this);
    ap_out = new("ap_out", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("GEMM_MON", "env_config not set")
    vif = cfg.gemm_vif;
    if (vif == null) `uvm_fatal("GEMM_MON", "gemm_vif is null")
    n_in = 0; n_out = 0; n_hold_viol = 0;
  endfunction

  // 状態: 0=IDLE, 1=RUN (start 済み done 待ち), 2=LATCH (done の次で C を読む),
  //       3=HOLD (次の start まで C が保持されることを確認)
  protected int unsigned st;
  protected int unsigned cyc;
  protected bit [32*4*4-1:0] c_seen;

  // **入れ子の待ちを作らないこと。** 内側で @(posedge) を回すと、その間の
  // wr_en と次の start を取りこぼす (最初の実装で踏んだ)。1 プロセス 1 posedge の
  // 平坦な状態機械にして、毎サイクルすべての事象を見る。
  task run_phase(uvm_phase phase);
    st = 0; cyc = 0; c_seen = '0;
    forever begin
      @(posedge vif.clk);
      #1;
      if (vif.rst_n !== 1'b1) begin
        st = 0;
        continue;
      end
      // バッファ書き込みは状態によらず毎サイクル拾う
      if (vif.wr_en === 1'b1) capture_write();

      if (st == 0) begin
        if (vif.start === 1'b1) begin
          publish_in();
          cyc = 1;
          st  = 1;
        end
      end else if (st == 1) begin
        cyc++;
        if (vif.done === 1'b1) st = 2;
        else if (cyc > 500) begin
          `uvm_error("GEMM_MON", "timeout waiting for done")
          st = 0;
        end
      end else if (st == 2) begin
        // C は done アサートのサイクル末にラッチされるので、その次で読む (8.6 節)
        c_seen = vif.c_flat;
        publish_out(c_seen, cyc);
        st = 3;
      end else begin
        if (vif.start === 1'b1) begin
          publish_in();
          cyc = 1;
          st  = 1;
        end else if (vif.c_flat !== c_seen) begin
          n_hold_viol++;
          `uvm_error("GEMM_MON_HOLD",
            "C changed after done and before the next start (spec 8.6 requires it to be held)")
          st = 0;
        end
      end
    end
  endtask

  // wr_en のサイクルを 1 件ずつ拾う。ループもハンドル呼び出しも無い。
  task capture_write();
    int unsigned idx, r, k;
    idx = vif.wr_addr;
    r   = idx / 4;
    k   = idx % 4;
    if (r < 4 && k < 4) begin
      if (vif.wr_sel === 1'b0) obs_a[r][k] = vif.wr_data;
      else                     obs_b[r][k] = vif.wr_data;
    end
  endtask

  task publish_in();
    gemm_item tr;
    tr = gemm_item::type_id::create("mon_in");
    tr.alloc(4, 4, 4);
    gemm_copy_bufs(obs_a, obs_b, tr);
    ap_in.write(tr);
    n_in++;
  endtask

  task publish_out(input bit [32*4*4-1:0] c, input int unsigned cy);
    gemm_result_item tr;
    tr = gemm_result_item::type_id::create("mon_out");
    tr.c_flat      = c;
    tr.done_cycles = cy;
    ap_out.write(tr);
    n_out++;
  endtask

  function void report_phase(uvm_phase phase);
    `uvm_info("GEMM_MON", $sformatf("in=%0d out=%0d hold-violations=%0d",
                                    n_in, n_out, n_hold_viol), UVM_LOW)
  endfunction
endclass

// -----------------------------------------------------------------------------
// gemm_agent (A.5.3)
// -----------------------------------------------------------------------------
class gemm_agent extends uvm_agent;
  `uvm_component_utils(gemm_agent)

  env_config                 cfg;
  gemm_driver                drv;
  uvm_sequencer #(gemm_item) gemm_sequencer;
  gemm_monitor               mon;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("GEMM_AGT", "env_config not set")
    uvm_config_db#(env_config)::set(this, "*", "cfg", cfg);

    mon = gemm_monitor::type_id::create("mon", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      drv            = gemm_driver::type_id::create("drv", this);
      gemm_sequencer = uvm_sequencer #(gemm_item)::type_id::create("gemm_sequencer", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    if (cfg.is_active == UVM_ACTIVE)
      drv.seq_item_port.connect(gemm_sequencer.seq_item_export);
  endfunction
endclass
