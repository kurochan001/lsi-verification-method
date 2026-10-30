// -----------------------------------------------------------------------------
// mxfp4_fifo
//   汎用の同期 FIFO (first-word fall-through)。仕様書 3.3 節の ready 拡張で
//   使うバッファ。valid/ready ハンドシェイクを両側に持つ。
//
//   ハンドシェイク規約 (仕様書 3.3 節。AMBA AXI §A3.2.1 と同じ規約):
//     - 転送が起きるのは valid と ready が同時に 1 のクロックエッジ。
//     - ソースは valid を立てたら転送が起きるまで valid とデータを保持する。
//     - デスティネーションは valid を待ってから ready を立ててよい。
//
//   wr_ready は count レジスタだけから決まるので rd_ready へ組合せ依存しない。
//   したがって本 FIFO を挟めば、下流 (mxfp4_bdp) が持つ out_ready -> in_ready の
//   組合せパスを上流から切り離せる (AXI §A3.2.1 が禁じる入力->出力の組合せパス)。
//
//   FWFT なので rd_data は mem からの組合せ読み出しになる。段数の浅い
//   レジスタファイルを想定した学習用の簡略実装である (仕様書 8.8 節と同じ方針)。
// -----------------------------------------------------------------------------
module mxfp4_fifo #(
  parameter int WIDTH = 8,
  parameter int DEPTH = 4,                            // 2 以上
  // 以下は導出パラメータ。上書きしないこと。
  parameter int PTR_W = (DEPTH > 1) ? $clog2(DEPTH) : 1,
  parameter int CNT_W = $clog2(DEPTH + 1)
) (
  input  logic             clk,
  input  logic             rst_n,
  // ---- 書き込み側 ----
  input  logic             wr_valid,
  output logic             wr_ready,
  input  logic [WIDTH-1:0] wr_data,
  // ---- 読み出し側 ----
  output logic             rd_valid,
  input  logic             rd_ready,
  output logic [WIDTH-1:0] rd_data,
  // ---- 観測ポート (合成時は削除可) ----
  output logic [CNT_W-1:0] level_dbg
);

  initial begin
    if (DEPTH < 2)
      $fatal(1, "mxfp4_fifo: DEPTH must be >= 2 (got %0d)", DEPTH);
  end

  logic [WIDTH-1:0] mem [DEPTH];
  logic [PTR_W-1:0] wr_ptr, rd_ptr;
  logic [CNT_W-1:0] count;
  logic             push, pop;

  assign wr_ready  = (count != CNT_W'(DEPTH));
  assign rd_valid  = (count != CNT_W'(0));
  assign level_dbg = count;

  // mem はリセットを持たない (仕様書 8.8 節と同じ簡略方式) ため、空のあいだ
  // mem[rd_ptr] は未初期化。4-state シミュレータではそれが下流のデータパスへ
  // X として伝播し、e2m1_decode の unique case を無意味に発火させる。
  // rd_valid = 0 のときの rd_data は規約上どのみち意味を持たないので、
  // ここでゼロに落として X 伝播を止める。
  assign rd_data = rd_valid ? mem[rd_ptr] : '0;

  assign push = wr_valid & wr_ready;
  assign pop  = rd_valid & rd_ready;

  always_ff @(posedge clk) begin
    if (push) mem[wr_ptr] <= wr_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
      count  <= '0;
    end else begin
      // DEPTH は 2 のべきとは限らないので明示的にラップさせる
      if (push) wr_ptr <= (wr_ptr == PTR_W'(DEPTH-1)) ? '0 : wr_ptr + PTR_W'(1);
      if (pop)  rd_ptr <= (rd_ptr == PTR_W'(DEPTH-1)) ? '0 : rd_ptr + PTR_W'(1);
      unique case ({push, pop})
        2'b10:   count <= count + CNT_W'(1);
        2'b01:   count <= count - CNT_W'(1);
        default: count <= count;          // 2'b00 / 2'b11 は増減なし
      endcase
    end
  end

`ifdef MXFP4_ASSERT
  // 空から読まない / 満杯へ書かない (ハンドシェイク規約の内部整合)
  a_fifo_no_overflow: assert property (@(posedge clk) disable iff (!rst_n)
      push |-> (count < CNT_W'(DEPTH)))
    else $error("mxfp4_fifo: push while full");

  a_fifo_no_underflow: assert property (@(posedge clk) disable iff (!rst_n)
      pop |-> (count > CNT_W'(0)))
    else $error("mxfp4_fifo: pop while empty");

  // 転送が起きるまでソースは valid とデータを保持する (仕様書 3.3 節)
  a_fifo_src_hold: assert property (@(posedge clk) disable iff (!rst_n)
      (wr_valid && !wr_ready) |=> (wr_valid && $stable(wr_data)))
    else $error("mxfp4_fifo: source dropped valid/data before acceptance");
`endif

endmodule
