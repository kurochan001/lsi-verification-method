// -----------------------------------------------------------------------------
// トランザクション定義 (付録A A.4.1 / A.4.2)
//
//   [付録A A.4.1 からの変更 — c_pack を post_randomize() へ移す]
//     A.4.1 は a_block / b_block を rand にして constraint c_pack で分解ビューと
//     結合するが、幅 136bit の rand 変数に part-select の等式制約を付けた状態で
//     in-line 制約を足すと sukimasim の制約ソルバが解けない
//     (sukimasim Issue #1167。幅 69bit 以上で発生)。
//     docs/spec_review_appendixA.md の提案どおり block を非 rand にし、
//     post_randomize() でパックする。制約は scale / elem の範囲・分布だけになる。
//     プレーン SV 版 (9 章) も同じ考え方でブロックを組み立てている。
//
//   post_randomize() には A.12.3 が推奨する制約充足のセルフチェックを入れる。
//   TB の誤りとシミュレータのソルバ不具合を切り分けるための仕掛け。
// -----------------------------------------------------------------------------

class blk_pair_item extends uvm_sequence_item;
  // ソルバの対象にしない (上記のとおり)
  bit [BLOCK_W-1:0] a_block;
  bit [BLOCK_W-1:0] b_block;

  rand bit          first;
  rand bit          last;
  // スケール / 要素の分解ビュー (制約記述用)
  rand bit [7:0]    a_scale, b_scale;
  rand bit [3:0]    a_elem [K];
  rand bit [3:0]    b_elem [K];

  `uvm_object_utils_begin(blk_pair_item)
    `uvm_field_int(a_block, UVM_ALL_ON)
    `uvm_field_int(b_block, UVM_ALL_ON)
    `uvm_field_int(first,   UVM_ALL_ON)
    `uvm_field_int(last,    UVM_ALL_ON)
  `uvm_object_utils_end

  function new(string name = "blk_pair_item");
    super.new(name);
  endfunction

  // 分解ビューを block へ結合 (2.3 節: scale = [135:128]、要素 i = [4*i +: 4])
  //
  //   [sukimasim Issue #1170 の回避]
  //     クラスメソッド内からクラスプロパティへ部分代入 (bit-select /
  //     part-select) すると、sukimasim 0.9.9.2 では直前の全体代入以降
  //     最初の 1 回しか反映されない。ローカル変数に組んでから全体代入する
  //     形にすれば正しく動く。最小再現は repro/class_prop_partsel_minimal.sv。
  function void pack_blocks();
    bit [BLOCK_W-1:0] ta, tb;
    ta[BLOCK_W-1 -: 8] = a_scale;
    tb[BLOCK_W-1 -: 8] = b_scale;
    foreach (a_elem[i]) begin
      ta[4*i +: 4] = a_elem[i];
      tb[4*i +: 4] = b_elem[i];
    end
    a_block = ta;
    b_block = tb;
  endfunction

  // A.12.3 が推奨する制約充足のセルフチェック
  function void check_pack();
    if (a_block[BLOCK_W-1 -: 8] !== a_scale || b_block[BLOCK_W-1 -: 8] !== b_scale)
      `uvm_fatal("ITEM_PACK", $sformatf("scale mismatch a=%02h/%02h b=%02h/%02h",
                 a_block[BLOCK_W-1 -: 8], a_scale, b_block[BLOCK_W-1 -: 8], b_scale))
    foreach (a_elem[i]) begin
      if (a_block[4*i +: 4] !== a_elem[i])
        `uvm_fatal("ITEM_PACK", $sformatf("a_elem[%0d] mismatch %01h != %01h",
                   i, a_block[4*i +: 4], a_elem[i]))
      if (b_block[4*i +: 4] !== b_elem[i])
        `uvm_fatal("ITEM_PACK", $sformatf("b_elem[%0d] mismatch %01h != %01h",
                   i, b_block[4*i +: 4], b_elem[i]))
    end
  endfunction

  function void post_randomize();
    pack_blocks();
    check_pack();
  endfunction

  // directed シーケンス用: randomize せずに値を与える
  function void set_blocks(input bit [7:0] sa, input bit [7:0] sb,
                           input bit [3:0] ea [K], input bit [3:0] eb [K]);
    a_scale = sa;
    b_scale = sb;
    foreach (ea[i]) a_elem[i] = ea[i];
    foreach (eb[i]) b_elem[i] = eb[i];
    pack_blocks();
    check_pack();
  endfunction

  function string convert2string();
    return $sformatf("a=%034h b=%034h first=%0b last=%0b",
                     a_block, b_block, first, last);
  endfunction
endclass

// -----------------------------------------------------------------------------
// 入力側トランザクション (monitor が in_valid && in_ready で発行)
//
//   [付録A A.5.2 / 図13 からの変更 — driver 用と monitor 用で型を分ける]
//     付録A は ap_in も blk_pair_item を運ぶ構成だが、sukimasim 0.9.9.2 では
//     sequencer / driver の型パラメータと同じ型を analysis 系
//     (uvm_analysis_imp / uvm_tlm_analysis_fifo) の型パラメータにも使うと、
//     その analysis 系にだけ write が届かなくなる
//     (同じ write でも uvm_subscriber には届く)。
//     監視側トランザクションを独立の型にすれば回避できる。役割 (刺激 / 観測) が
//     分かれるので設計としても素直になる。
// -----------------------------------------------------------------------------
class bdp_in_item extends uvm_sequence_item;
  bit [BLOCK_W-1:0] a_block;
  bit [BLOCK_W-1:0] b_block;
  bit               first;
  bit               last;

  `uvm_object_utils(bdp_in_item)

  function new(string name = "bdp_in_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("a=%034h b=%034h first=%0b last=%0b",
                     a_block, b_block, first, last);
  endfunction
endclass

// -----------------------------------------------------------------------------
// 出力側トランザクション (out_valid 契機)
// -----------------------------------------------------------------------------
class bdp_result_item extends uvm_sequence_item;
  bit [31:0] result;

  `uvm_object_utils_begin(bdp_result_item)
    `uvm_field_int(result, UVM_ALL_ON)
  `uvm_object_utils_end

  function new(string name = "bdp_result_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("result=%08h", result);
  endfunction
endclass

// -----------------------------------------------------------------------------
// 段別 dbg トランザクション (sop_valid_dbg / exp_valid_dbg 契機)
//   単一 covergroup を段違いの valid でサンプルすると別ブロックの値を拾う
//   (C1 / C7 の教訓)。モニタ側で段を分離するためのトランザクション。
// -----------------------------------------------------------------------------
class bdp_dbg_item extends uvm_sequence_item;
  bit signed [SOP4_W-1:0] sop4;
  bit signed [IEXP_W-1:0] exp_internal;

  `uvm_object_utils(bdp_dbg_item)

  function new(string name = "bdp_dbg_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("sop4=%0d exp_internal=%0d", sop4, exp_internal);
  endfunction
endclass

// -----------------------------------------------------------------------------
// エンコーダ用 (A.4.2)
// -----------------------------------------------------------------------------
class enc_item extends uvm_sequence_item;
  rand bit [31:0] v [K];
  // 生成モード (directed / random の切替。制約記述用)
  rand int unsigned mode;
  // 指数の窓 (レーン間で amax を意味のある範囲に収める)
  rand int unsigned emin, emax;

  `uvm_object_utils(enc_item)

  constraint c_win {
    emin inside {[1 : 240]};
    emax inside {[emin : emin + 12]};
    emax <= 254;
  }

  constraint c_mode { mode inside {[0 : 3]}; }

  function new(string name = "enc_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("enc_item mode=%0d emin=%0d emax=%0d v[0]=%08h",
                     mode, emin, emax, v[0]);
  endfunction
endclass

class enc_result_item extends uvm_sequence_item;
  bit [BLOCK_W-1:0]             blk;
  bit signed [SCALED_EXP_W-1:0] e_rel [K];
  bit [2:0]                     mag3  [K];
  bit                           tie   [K];

  `uvm_object_utils(enc_result_item)

  function new(string name = "enc_result_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("blk=%034h", blk);
  endfunction
endclass

// -----------------------------------------------------------------------------
// 加算器単体用 (A.4.2 / A.10、R2f)
//   同符号かつ指数差 1..30 を狙う制約 (桁上げ + sticky 経路) と、
//   完全相殺 (a_sign != b_sign、a_exp == b_exp、a_sig == b_sig) を切替可能にする。
// -----------------------------------------------------------------------------
// monitor が 1 サイクル分の観測 (入力 2 つと結果) をまとめて出すための item。
// 加算器は組合せなので入力と結果は同じ時刻に確定しており、段を分ける意味がない。
class addcore_obs_item extends uvm_sequence_item;
  bit [31:0] a_fp;
  bit [31:0] b_fp;
  bit [31:0] r_fp;        // r_zero のときは +0 (0x00000000)
  bit        r_zero;
  bit        r_carry_ovf;

  `uvm_object_utils(addcore_obs_item)

  function new(string name = "addcore_obs_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("%08h + %08h -> %08h (zero=%0b covf=%0b)",
                     a_fp, b_fp, r_fp, r_zero, r_carry_ovf);
  endfunction
endclass

class addcore_item extends uvm_sequence_item;
  rand bit                     a_sign, b_sign;
  rand bit signed [IEXP_W-1:0] a_exp,  b_exp;
  rand bit [SIGNIF_W-1:0]      a_sig,  b_sig;
  // 0: 同符号 + 指数差 1..30 / 1: 完全相殺 / 2: 一様
  rand int unsigned            mode;

  `uvm_object_utils(addcore_item)

  constraint c_norm {
    // 暗黙 1 込みの正規化仮数 (5.4 節)
    a_sig[SIGNIF_W-1] == 1'b1;
    b_sig[SIGNIF_W-1] == 1'b1;
    // FP32 の指数フィールド 1..254 に収まる範囲 (内部指数 = フィールド値)
    a_exp inside {[1 : 254]};
    b_exp inside {[1 : 254]};
  }

  constraint c_mode {
    mode dist { 0 := 70, 1 := 10, 2 := 20 };
    (mode == 0) -> (a_sign == b_sign &&
                    (b_exp - a_exp) inside {[1 : 30]});
    (mode == 1) -> (a_sign != b_sign && a_exp == b_exp && a_sig == b_sig);
  }

  function new(string name = "addcore_item");
    super.new(name);
  endfunction

  // FP32 ビットパターンへ (指数フィールド = 内部指数)
  function bit [31:0] a_fp32();
    return {a_sign, a_exp[7:0], a_sig[SIGNIF_W-2:0]};
  endfunction

  function bit [31:0] b_fp32();
    return {b_sign, b_exp[7:0], b_sig[SIGNIF_W-2:0]};
  endfunction

  // 制約充足のセルフチェック (付録A A.12.3 の推奨手法)。
  // ソルバの不具合と TB の誤りを切り分けるために置く。
  // ループもハンドル経由の呼び出しも使わない (Issue #1322 の条件を作らない)。
  bit sc_ok;
  function void post_randomize();
    sc_ok = 1'b1;
    if (a_sig[SIGNIF_W-1] !== 1'b1) sc_ok = 1'b0;
    if (b_sig[SIGNIF_W-1] !== 1'b1) sc_ok = 1'b0;
    if (!(a_exp inside {[1 : 254]})) sc_ok = 1'b0;
    if (!(b_exp inside {[1 : 254]})) sc_ok = 1'b0;
    if (mode == 0 && !(a_sign == b_sign && (b_exp - a_exp) inside {[1 : 30]}))
      sc_ok = 1'b0;
    if (mode == 1 && !(a_sign != b_sign && a_exp == b_exp && a_sig == b_sig))
      sc_ok = 1'b0;
  endfunction

  function string convert2string();
    return $sformatf("a=%08h b=%08h mode=%0d", a_fp32(), b_fp32(), mode);
  endfunction
endclass

class addcore_result_item extends uvm_sequence_item;
  bit                     r_sign;
  bit signed [IEXP_W-1:0] r_exp;
  bit [SIGNIF_W-1:0]      r_sig;
  bit                     r_carry_ovf;
  bit                     r_zero;

  `uvm_object_utils(addcore_result_item)

  function new(string name = "addcore_result_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("r_sign=%0b r_exp=%0d r_sig=%06h ovf=%0b zero=%0b",
                     r_sign, r_exp, r_sig, r_carry_ovf, r_zero);
  endfunction
endclass

// -----------------------------------------------------------------------------
// GEMM 用 (A.9、方式 Y)
//   A / B 行列をブロックで持ち、start から done までを 1 トランザクションとする。
// -----------------------------------------------------------------------------
// monitor が 1 回の GEMM 実行 (start -> done -> C 読み出し) をまとめて出す item。
// C は packed のまま持つ (要素 (r,c) = c_flat[32*(r*COLS+c) +: 32])。
// 2 次元 unpacked をクラスに持たせても構わないが、gemm_if を packed に
// 畳んでいるので (Issue #1320)、同じ表現のまま運ぶ方が経路が短い。
class gemm_result_item extends uvm_sequence_item;
  bit [32*4*4-1:0] c_flat;
  int unsigned     done_cycles;   // start から done までのサイクル数

  `uvm_object_utils(gemm_result_item)

  function new(string name = "gemm_result_item");
    super.new(name);
  endfunction

  function bit [31:0] c_at(input int unsigned r, input int unsigned c, input int unsigned cols = 4);
    return c_flat[32*(r*cols + c) +: 32];
  endfunction

  function string convert2string();
    return $sformatf("gemm_result done_cycles=%0d C[0][0]=%08h", done_cycles, c_at(0, 0));
  endfunction
endclass

class gemm_item extends uvm_sequence_item;
  bit [BLOCK_W-1:0] a_mat [][];   // [ROWS][KBLK]
  bit [BLOCK_W-1:0] b_mat [][];   // [COLS][KBLK]
  int unsigned      rows, cols, kblk;

  `uvm_object_utils(gemm_item)

  function new(string name = "gemm_item");
    super.new(name);
  endfunction

  function void alloc(int unsigned r, int unsigned c, int unsigned k);
    rows = r; cols = c; kblk = k;
    a_mat = new[r];
    foreach (a_mat[i]) a_mat[i] = new[k];
    b_mat = new[c];
    foreach (b_mat[i]) b_mat[i] = new[k];
  endfunction

  function string convert2string();
    return $sformatf("gemm_item rows=%0d cols=%0d kblk=%0d", rows, cols, kblk);
  endfunction
endclass

class gemm_result_item extends uvm_sequence_item;
  bit [31:0]   c_mat [][];
  int unsigned done_cycles;   // start から done までのサイクル数 (A.9.2)

  `uvm_object_utils(gemm_result_item)

  function new(string name = "gemm_result_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("gemm_result done_cycles=%0d", done_cycles);
  endfunction
endclass
