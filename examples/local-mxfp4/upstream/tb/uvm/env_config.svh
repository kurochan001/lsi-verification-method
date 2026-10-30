// -----------------------------------------------------------------------------
// env_config
//   付録A A.2.3 節の config オブジェクト。uvm_config_db 経由で env / agent へ
//   配布する。virtual interface も本オブジェクトに格納して渡す (A.3.3 の推奨)。
//
//   [付録A A.2.3 への追加 — clk_period]
//     A.8.1 の骨格は drain time に定数 20 (= 20 ns) を与えているが、
//     LAT = 6 は周期 10 ns で 60 ns に相当し足りない
//     (docs/spec_review_appendixA.md A-2)。周期を config から受け取り
//     (LAT + 余裕) x clk_period で算出する。
// -----------------------------------------------------------------------------
class env_config extends uvm_object;
  `uvm_object_utils(env_config)

  uvm_active_passive_enum is_active      = UVM_ACTIVE;
  bit                     has_scoreboard = 1'b1;
  bit                     has_coverage   = 1'b1;
  int unsigned            num_blocks     = 100;
  time                    clk_period     = 10ns;

  // カバレッジ閉包を要求するか (単一テストでは 100% にならないので、
  // 全シーケンスを流すレグレッションテストでのみ 1 にする)
  bit                     check_coverage = 1'b0;
  // 隙間なし連続投入が実際に起きたことを要求するか (A-1 の裏付け)
  bit                     check_b2b      = 1'b1;

  // 段階 7 のパラメータ。RTL 側の GRADUAL_UF と揃えるとリファレンスも切り替わる
  // (既定は Rev.1.3 の規範どおり FTZ)。
  bit                     gradual_uf     = 1'b0;
  // 7.7 節の 3/4 スケーリング。quant_encoder の UNBIASED_34 と揃えると
  // リファレンス (ref_encode_block_ex) も切り替わる。既定は Algorithm 1。
  bit                     unbiased_34    = 1'b0;

  virtual bdp_if     bdp_vif;
  virtual enc_if     enc_vif;
  virtual addcore_if addcore_vif;
  virtual gemm_if    gemm_vif;

  function new(string name = "env_config");
    super.new(name);
  endfunction

  // drain time (A-2)。LAT 段のパイプラインを吐き切る + 余裕 4 サイクル。
  function time drain_time();
    return (mxfp4_pkg::LAT + 4) * clk_period;
  endfunction

  // エンコーダ版 (段数が ENC_LAT = 5 なのでこちらを使う)
  function time enc_drain_time();
    return (mxfp4_pkg::ENC_LAT + 4) * clk_period;
  endfunction
endclass
