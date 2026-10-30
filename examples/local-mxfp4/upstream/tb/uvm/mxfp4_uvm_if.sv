// -----------------------------------------------------------------------------
// mxfp4_uvm_if
//   付録A A.3 節のインターフェース群。
//     bdp_if     : mxfp4_bdp 用 (A.3.1)
//     enc_if     : quant_encoder 用 (A.3.2)
//     addcore_if : mxfp4_fp32_add_core 用 (A.3.2、R2f)
//     gemm_if    : mxfp4_gemm_top 用 (A.9、方式 Y)
//
//   [付録A A.3.1 への追加 1 — 観測用 clocking block]
//     A.3.1 は clocking block を cb 1 つだけ規定し、modport mp_mon を
//     「観測専用」としている。しかし cb の output (a_block 等) を monitor から
//     読むと driver が最後に書いた値が返り、DUT が実際に受け取った値の観測に
//     ならない。入力専用の cb_mon を分けて monitor 側に与える。
//
//   [付録A A.3.1 への追加 2 — out_ready]
//     A.3.1 の信号表に out_ready がない。RTL は 3.3 節の ready 拡張を実装して
//     いるので、インターフェースにも収容して hw_top で 1 固定にする
//     (バックプレッシャの検証はプレーン SV 版 tb_bdp_flow が担当する)。
//
//   宣言時初期値は付けない (Verilator の PROCASSINIT。README の落とし穴 1)。
//   初期化は hw_top のリセットシーケンスで行う。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

interface bdp_if (input logic clk);
  import mxfp4_pkg::*;

  logic                     rst_n;
  logic                     in_valid;
  logic                     in_ready;
  logic [BLOCK_W-1:0]       a_block;
  logic [BLOCK_W-1:0]       b_block;
  logic                     first;
  logic                     last;
  logic                     out_valid;
  logic                     out_ready;
  logic [31:0]              result;
  // 観測ポート (仕様書 4.6 節)
  logic signed [SOP4_W-1:0] sop4_dbg;
  logic                     sop_valid_dbg;
  logic signed [IEXP_W-1:0] exp_internal_dbg;
  logic                     exp_valid_dbg;

  // driver 駆動用
  clocking cb @(posedge clk);
    default input #1step output #1;
    output in_valid, a_block, b_block, first, last;
    input  in_ready, out_valid, result;
  endclocking

  // monitor 観測用 (上記「追加 1」)
  clocking cb_mon @(posedge clk);
    default input #1step;
    input in_valid, in_ready, a_block, b_block, first, last,
          out_valid, out_ready, result,
          sop4_dbg, sop_valid_dbg, exp_internal_dbg, exp_valid_dbg;
  endclocking

  modport mp_drv (clocking cb,     input clk, rst_n);
  modport mp_mon (clocking cb_mon, input clk, rst_n);
endinterface

// -----------------------------------------------------------------------------
// enc_if : quant_encoder (A.3.2)
//
//   [付録A A.3.2 からの変更 — メンバをすべて packed にする]
//     付録A は v_i / e_rel_dbg / mag3_dbg / tie_hit_dbg を DUT と同じ
//     unpacked 配列でインターフェースに置く形を示しているが、sukimasim
//     0.9.9.2 では **interface の unpacked 配列がモジュールのポートへ
//     接続されていると、その配列への書き込みが届かない** (Issue #1320)。
//     TB 側から書いても interface 自身の always_comb から書いても落ち、
//     DUT は全ゼロを受け取る。しかも全ゼロ入力は全ゼロ出力と一致するため、
//     スコアボードは vacuous に通ってしまい気付けない (実際に踏んだ)。
//
//     そこでインターフェースは packed ベクタだけを持ち、unpacked 配列への
//     展開・収集は hw_enc_top の module スコープで行う。module スコープの
//     unpacked 配列はポートへ繋いでも正しく動く。BDP 用の bdp_if が
//     無事だったのも全メンバが packed だからで、同じ方針に揃えたことになる。
//
//     要素 i は常に `[W*i +: W]` に置く (hw_enc_top と monitor で共通)。
// -----------------------------------------------------------------------------
interface enc_if (input logic clk);
  import mxfp4_pkg::*;

  logic                     rst_n;
  logic                     in_valid;
  logic [32*K-1:0]          v_flat;         // DUT の v_i (要素 i = [32*i +: 32])
  logic [BLOCK_W-1:0]       blk_o;
  logic                     out_valid;
  // 観測ポート (仕様書 7.6 節)。いずれも packed に畳んである。
  logic [SCALED_EXP_W*K-1:0] e_rel_flat;    // DUT の e_rel_dbg (signed として読む)
  logic [3*K-1:0]            mag3_flat;     // DUT の mag3_dbg
  logic [K-1:0]              tie_flat;      // DUT の tie_hit_dbg
  logic                      quant_valid_dbg;
endinterface

// -----------------------------------------------------------------------------
// addcore_if : mxfp4_fp32_add_core (A.3.2、R2f)
//   加算器は組合せ回路なので、TB 側のサンプルクロック (clk) に同期させる。
//
//   [付録A A.3.2 への追加 — rst_n / in_valid]
//     A.3.2 の信号表はデータ端子だけを挙げているが、DUT が組合せである以上
//     「いつの値が 1 件の観測なのか」を決める印が要る。driver が negedge で
//     駆動して in_valid を立て、monitor が posedge で 1 件として採る。
//     これが無いと、駆動していない時刻の未定義値まで観測してしまう。
//     rst_n は driver / monitor の開始点を揃えるためだけに使う (DUT へは繋がない)。
//
//     メンバはすべて packed / スカラ。unpacked 配列を置くと Issue #1320 を踏む。
// -----------------------------------------------------------------------------
interface addcore_if (input logic clk);
  import mxfp4_pkg::*;

  logic                     rst_n;
  logic                     in_valid;
  logic                     a_sign;
  logic signed [IEXP_W-1:0] a_exp;
  logic [SIGNIF_W-1:0]      a_sig;
  logic                     b_sign;
  logic signed [IEXP_W-1:0] b_exp;
  logic [SIGNIF_W-1:0]      b_sig;
  logic                     r_sign;
  logic signed [IEXP_W-1:0] r_exp;
  logic [SIGNIF_W-1:0]      r_sig;
  logic                     r_carry_ovf;
  logic                     r_zero;
endinterface

// -----------------------------------------------------------------------------
// gemm_if : mxfp4_gemm_top (A.9 方式 Y)
//
//   [付録A A.9 からの変更 — c_o を packed に畳む]
//     付録A の信号表は結果を `logic [31:0] c_o [ROWS][COLS]` と 2 次元の
//     unpacked 配列で持たせているが、sukimasim 0.9.9.2 では interface の
//     unpacked 配列をモジュールのポートへ繋ぐと書き込みが届かない
//     (Issue #1320)。DUT が全ゼロを返しているように見え、しかも
//     期待値も全ゼロになるため**スコアボードが vacuous に一致して通る**。
//     そこでインターフェースは packed ベクタだけを持ち、2 次元への展開は
//     hw_gemm_top の module スコープで行う (enc_if と同じ方針)。
//     要素 (r, c) は [32*(r*COLS + c) +: 32] に置く。
//
//   [付録A A.9.2 への対応 — done サイクル計数]
//     start から done までのサイクル数を monitor が数え、scoreboard が
//     1 + KBLK + LAT と照合する。そのために start / done / busy を収容する。
// -----------------------------------------------------------------------------
interface gemm_if #(
  parameter int ROWS   = 4,
  parameter int COLS   = 4,
  parameter int ADDR_W = 4
) (input logic clk);
  import mxfp4_pkg::*;

  logic                    rst_n;
  logic                    start;
  logic                    wr_en;
  logic                    wr_sel;
  logic [ADDR_W-1:0]       wr_addr;
  logic [BLOCK_W-1:0]      wr_data;
  logic                    busy;
  logic                    done;
  // 結果 C。要素 (r, c) = c_flat[32*(r*COLS + c) +: 32]
  logic [32*ROWS*COLS-1:0] c_flat;
endinterface
