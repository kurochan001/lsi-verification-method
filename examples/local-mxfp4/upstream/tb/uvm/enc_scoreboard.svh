// -----------------------------------------------------------------------------
// enc_scoreboard (付録A A.6 を quant_encoder レベルへ適用したもの)
//   in-order 比較。quant_encoder は ENC_LAT = 5 段の素直なパイプラインで
//   投入順 = 出力順なので、キューで足りる。
//
//   基準器は mxfp4_ref_pkg::ref_encode_block_ex() (仕様書 7.2 節の区間表を
//   実数比較でそのまま実装したもの)。RTL の相対指数 + M1/G/S 方式とは独立に
//   書かれているので、両者の一致が意味を持つ (A.6.1)。
//
//   受け口を uvm_subscriber にするのは BDP 版と同じ理由
//   (sukimasim 0.9.9.2 では analysis fifo へ write したものが get() 側へ
//    届かない。docs/spec_review_appendixA.md 5.2 節)。
//
//   タイ点の厳密照合は directed 系 (d5b_tie_seq) のときだけ行う。
//   基準器側にタイ判定を新設すると RTL とリファレンスの独立性が崩れるので、
//   「d = 0 の要素だけ tie_hit が立つ」という D5b の性質は
//   シーケンスが仕込んだ既知パターンに対してのみ検査する (check_tie で切替)。
// -----------------------------------------------------------------------------

typedef class enc_scoreboard;

// 投入側の受け口
class encsb_in_sub extends uvm_subscriber #(enc_item);
  `uvm_component_utils(encsb_in_sub)
  enc_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(enc_item t);
    sb.on_in(t);
  endfunction
endclass

// 出力側の受け口
class encsb_out_sub extends uvm_subscriber #(enc_result_item);
  `uvm_component_utils(encsb_out_sub)
  enc_scoreboard sb;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void write(enc_result_item t);
    sb.on_out(t);
  endfunction
endclass

class enc_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(enc_scoreboard)

  encsb_in_sub  sub_in;
  encsb_out_sub sub_out;

  env_config cfg;

  // 期待値キュー (in-order)
  bit [135:0] exp_q [$];
  // 不一致報告用に、対応する入力ブロックの先頭要素も持っておく
  bit [31:0]  in_head_q [$];

  int unsigned n_check, n_mismatch;

  // R3 の統計 (仕様書 9.3 節 R3: クランプ / フラッシュ率をログ)
  int unsigned n_elem, n_clamp, n_flush;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    n_check = 0; n_mismatch = 0;
    n_elem  = 0; n_clamp    = 0; n_flush = 0;
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("ENC_SB", "env_config not set")
    sub_in  = encsb_in_sub ::type_id::create("sub_in",  this);
    sub_out = encsb_out_sub::type_id::create("sub_out", this);
    sub_in.sb  = this;
    sub_out.sb = this;
  endfunction

  // 投入を受けたら期待値を作ってキューへ積む
  function void on_in(enc_item t);
    logic [31:0] v_loc [32];
    bit [135:0]  exp;
    for (int i = 0; i < 32; i++) v_loc[i] = t.v[i];
    // スコープ解決を付けずに呼ぶ (mxfp4_scoreboard.svh の注記と同じ運用)
    exp = ref_encode_block_ex(v_loc, cfg.unbiased_34);
    exp_q.push_back(exp);
    in_head_q.push_back(t.v[0]);
  endfunction

  // 出力を受けたら先頭の期待値と照合する
  function void on_out(enc_result_item t);
    bit [135:0] exp;
    bit [31:0]  head;
    if (exp_q.size() == 0) begin
      `uvm_error("ENC_SB", $sformatf("unexpected result with no pending block: blk=%034h", t.blk))
      return;
    end
    exp  = exp_q.pop_front();
    head = in_head_q.pop_front();
    n_check++;
    if (t.blk !== exp) begin
      n_mismatch++;
      `uvm_error("ENC_SB", $sformatf(
        "block mismatch: v[0]=%08h\n  exp=%034h\n  got=%034h\n  exp scale=%02h got scale=%02h",
        head, exp, t.blk, exp[135:128], t.blk[135:128]))
    end
    collect_stats(t.blk);
  endfunction

  // クランプ / フラッシュ率 (R3 のログ要件)
  function void collect_stats(bit [135:0] blk);
    bit [2:0] mag;
    if (blk[135:128] == 8'hFF || blk[135:128] == 8'h00) return;  // NaN / 全ゼロブロック
    for (int i = 0; i < 32; i++) begin
      mag = blk[4*i +: 3];
      n_elem++;
      if (mag == 3'b111) n_clamp++;
      if (mag == 3'b000) n_flush++;
    end
  endfunction

  function void check_phase(uvm_phase phase);
    if (exp_q.size() != 0)
      `uvm_error("ENC_SB", $sformatf("%0d block(s) driven but never came out", exp_q.size()))
    if (n_check == 0)
      `uvm_error("ENC_SB_EMPTY", "scoreboard did not compare anything")
  endfunction

  function void report_phase(uvm_phase phase);
    `uvm_info("ENC_SB", $sformatf("block checks=%0d, mismatches=%0d", n_check, n_mismatch), UVM_LOW)
    if (n_elem > 0)
      `uvm_info("ENC_SB", $sformatf("elements=%0d  clamped(111)=%0d (%0.3f%%)  flushed(000)=%0d (%0.3f%%)",
                n_elem, n_clamp, 100.0 * real'(n_clamp) / real'(n_elem),
                n_flush, 100.0 * real'(n_flush) / real'(n_elem)), UVM_LOW)
  endfunction
endclass
