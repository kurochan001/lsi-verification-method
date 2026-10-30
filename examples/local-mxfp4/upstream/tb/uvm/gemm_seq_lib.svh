// -----------------------------------------------------------------------------
// gemm_seq_lib (付録A A.9、シナリオ E3)
//   1 item = 1 回の GEMM 実行 (A / B のロード + start + done 待ち)。
//
//   **制約付きランダムで「必ず踏みたいケース」を担保しない** (落とし穴 4j)。
//   sukimasim 0.9.9.2 は dist の重みを無視することがある (Issue #1323) ので、
//   単位行列・NaN 伝播はいずれも directed で確実に作る。
// -----------------------------------------------------------------------------

virtual class gemm_base_seq extends uvm_sequence #(gemm_item);

  function new(string name = "gemm_base_seq");
    super.new(name);
  endfunction

  // 全ゼロブロック (scale = 0x00)
  static function bit [BLOCK_W-1:0] blk_zero();
    return {8'h00, 128'd0};
  endfunction

  // 単位行列の対角に置くブロック: 要素 0 だけ 1.0 (E2M1 コード 010)、残りゼロ。
  // scale = 127 (X = 1.0) なので、この 1 ブロックとの内積は相手の要素 0 を返す。
  static function bit [BLOCK_W-1:0] blk_one_at0();
    bit [127:0] el;
    el = 128'd0;
    el[3:0] = 4'b0010;          // sign=0, mag3=010 -> 1.0
    return {8'd127, el};
  endfunction

  // ランダムブロック (scale は 1..254、要素は一様)
  static function bit [BLOCK_W-1:0] blk_rand();
    bit [127:0] el;
    bit [7:0]   sc;
    sc = 8'($urandom_range(1, 254));
    for (int i = 0; i < 32; i++) el[4*i +: 4] = 4'($urandom_range(0, 15));
    return {sc, el};
  endfunction

  // NaN ブロック (scale = 0xFF。仕様書 7.5 節)
  static function bit [BLOCK_W-1:0] blk_nan();
    return {8'hFF, 128'd0};
  endfunction
endclass

// -----------------------------------------------------------------------------
// e3_identity_seq : 単位行列 x 任意行列 (仕様書 9.3 節 E3)
//   A を単位行列にすると C = B になる。**この形は非 vacuous 性の要でもある** —
//   全ゼロが流れていると C も期待値も全ゼロで一致してしまうため、
//   scoreboard 側で「C に非ゼロがあること」を要求している。
// -----------------------------------------------------------------------------
class e3_identity_seq extends gemm_base_seq;
  `uvm_object_utils(e3_identity_seq)

  function new(string name = "e3_identity_seq");
    super.new(name);
  endfunction

  task body();
    gemm_item tr;
    tr = gemm_item::type_id::create("tr");
    start_item(tr);
    tr.alloc(4, 4, 4);
    // A: 行 r の k = r だけ「要素 0 が 1.0」、他は全ゼロ
    for (int r = 0; r < 4; r++)
      for (int k = 0; k < 4; k++)
        tr.a_mat[r][k] = (r == k) ? blk_one_at0() : blk_zero();
    // B: 任意 (ランダム)
    for (int c = 0; c < 4; c++)
      for (int k = 0; k < 4; k++)
        tr.b_mat[c][k] = blk_rand();
    finish_item(tr);
  endtask
endclass

// -----------------------------------------------------------------------------
// e3_rand_seq : ランダム A / B のビット一致
// -----------------------------------------------------------------------------
class e3_rand_seq extends gemm_base_seq;
  `uvm_object_utils(e3_rand_seq)

  int unsigned n_runs = 20;

  function new(string name = "e3_rand_seq");
    super.new(name);
  endfunction

  task body();
    gemm_item tr;
    for (int t = 0; t < int'(n_runs); t++) begin
      tr = gemm_item::type_id::create("tr");
      start_item(tr);
      tr.alloc(4, 4, 4);
      for (int r = 0; r < 4; r++)
        for (int k = 0; k < 4; k++)
          tr.a_mat[r][k] = blk_rand();
      for (int c = 0; c < 4; c++)
        for (int k = 0; k < 4; k++)
          tr.b_mat[c][k] = blk_rand();
      finish_item(tr);
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// e3_nan_seq : NaN スケールの伝播 (仕様書 7.5 節 / 9.3 節 E3)
//   B の列 2 に NaN ブロックを 1 つ置くと、その列の C がすべて qNaN になる。
// -----------------------------------------------------------------------------
class e3_nan_seq extends gemm_base_seq;
  `uvm_object_utils(e3_nan_seq)

  function new(string name = "e3_nan_seq");
    super.new(name);
  endfunction

  task body();
    gemm_item tr;
    tr = gemm_item::type_id::create("tr");
    start_item(tr);
    tr.alloc(4, 4, 4);
    for (int r = 0; r < 4; r++)
      for (int k = 0; k < 4; k++)
        tr.a_mat[r][k] = blk_rand();
    for (int c = 0; c < 4; c++)
      for (int k = 0; k < 4; k++)
        tr.b_mat[c][k] = blk_rand();
    tr.b_mat[2][0] = blk_nan();      // 列 2 に NaN を 1 つ
    finish_item(tr);
  endtask
endclass
