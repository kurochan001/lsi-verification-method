// -----------------------------------------------------------------------------
// カバレッジ subscriber (付録A A.7)
//   uvm_subscriber#(T) を継承した段別カバレッジコンポーネントを、モニタの
//   各 analysis port に接続する。9.4 節の covergroup と bins を維持する。
//
//   段分離 (A.7.3): 各 subscriber は自身が担当する段のトランザクションだけを
//   受けるので、単一 covergroup を段違いの valid でサンプルして別ブロックの値を
//   拾う問題 (C1 / C7 の教訓) が構造的に起きない。
// -----------------------------------------------------------------------------

// 入力段 (ap_in、in_valid 契機)
class cov_bdp_in extends uvm_subscriber #(bdp_in_item);
  `uvm_component_utils(cov_bdp_in)

  bit [7:0] c_a_scale, c_b_scale;
  bit       c_first, c_last;
  int unsigned n_sample;

  covergroup cg_bdp_in;
    cp_a_scale: coverpoint c_a_scale {
      bins zero = {8'h00};
      bins mid  = {[8'h01:8'hFE]};
      bins nan  = {8'hFF};
    }
    cp_b_scale: coverpoint c_b_scale {
      bins zero = {8'h00};
      bins mid  = {[8'h01:8'hFE]};
      bins nan  = {8'hFF};
    }
    cp_first: coverpoint c_first;
    cp_last:  coverpoint c_last;
    // 1 ブロック列 (first & last 同時) を含む全 4 組合せ
    cp_first_last: cross cp_first, cp_last;
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    cg_bdp_in = new();
    n_sample  = 0;
  endfunction

  function void write(bdp_in_item t);
    c_a_scale = t.a_block[BLOCK_W-1 -: 8];
    c_b_scale = t.b_block[BLOCK_W-1 -: 8];
    c_first   = t.first;
    c_last    = t.last;
    cg_bdp_in.sample();
    n_sample++;
  endfunction

  function real coverage();
    return cg_bdp_in.get_coverage();
  endfunction
endclass

// SoP4 段 (ap_sop、sop_valid_dbg 契機)
class cov_bdp_sop extends uvm_subscriber #(bdp_dbg_item);
  `uvm_component_utils(cov_bdp_sop)

  bit signed [SOP4_W-1:0] c_sop4;
  int unsigned n_sample;

  covergroup cg_bdp_sop;
    cp_sop_sign: coverpoint c_sop4[SOP4_W-1];
    cp_sop_zero: coverpoint (c_sop4 == '0);
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    cg_bdp_sop = new();
    n_sample   = 0;
  endfunction

  function void write(bdp_dbg_item t);
    c_sop4 = t.sop4;
    cg_bdp_sop.sample();
    n_sample++;
  endfunction

  function real coverage();
    return cg_bdp_sop.get_coverage();
  endfunction
endclass

// 指数段 (ap_exp、exp_valid_dbg 契機)
class cov_bdp_exp extends uvm_subscriber #(bdp_dbg_item);
  `uvm_component_utils(cov_bdp_exp)

  bit signed [IEXP_W-1:0] c_exp;
  int unsigned n_sample;

  covergroup cg_bdp_exp;
    cp_exp_region: coverpoint c_exp {
      bins uf   = {[-300:0]};
      bins norm = {[1:254]};
      bins ovf  = {[255:400]};
    }
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    cg_bdp_exp = new();
    n_sample   = 0;
  endfunction

  function void write(bdp_dbg_item t);
    c_exp = t.exp_internal;
    cg_bdp_exp.sample();
    n_sample++;
  endfunction

  function real coverage();
    return cg_bdp_exp.get_coverage();
  endfunction
endclass

// -----------------------------------------------------------------------------
// cg_enc (A.7.2)
//   clocking event を持たず 32 レーンを明示 sample() する既存規約を維持する。
//   enc_monitor が quant_valid_dbg のサイクルで 32 レーン分を格納した
//   トランザクションを発行し、ここで foreach でレーンごとに sample() する。
// -----------------------------------------------------------------------------
class cov_enc extends uvm_subscriber #(enc_result_item);
  `uvm_component_utils(cov_enc)

  bit [2:0]                     c_mag3;
  bit signed [SCALED_EXP_W-1:0] c_erel;
  bit                           c_tie;
  int unsigned n_sample;

  covergroup cg_enc;
    cp_code: coverpoint c_mag3 { bins all_codes[] = {[0:7]}; }
    cp_erel: coverpoint c_erel {
      // 仕様書の bins low = {[-10:-3]} では実際の値域 (-254..2) を覆えないため
      // 下限を拡張した (9.4 節に対する既存の修正)。
      bins low  = {[-300:-3]};
      bins b_m2 = {-2};
      bins b_m1 = {-1};
      bins b0   = {0};
      bins b1   = {1};
      bins b2   = {2};
      // e_rel >= 3 は quant_encoder では構造的に発生しない
      ignore_bins hi = {[3:10]};
    }
    cp_tie: coverpoint c_tie;
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    cg_enc   = new();
    n_sample = 0;
  endfunction

  function void write(enc_result_item t);
    foreach (t.mag3[i]) begin
      c_mag3 = t.mag3[i];
      c_erel = t.e_rel[i];
      c_tie  = t.tie[i];
      cg_enc.sample();
      n_sample++;
    end
  endfunction

  function real coverage();
    return cg_enc.get_coverage();
  endfunction
endclass
