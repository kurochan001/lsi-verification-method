// -----------------------------------------------------------------------------
// BDP シーケンスライブラリ (付録A A.4.3 / A.4.4 / A.4.5、A.8 対応表)
//   各シーケンスは 9.3 節のシナリオ ID と 1 対 1 で対応する。
//   directed 系は randomize() を通さず set_blocks() で値を与える
//   (制約ソルバに依存しないので、シミュレータ差分の切り分けが楽になる)。
// -----------------------------------------------------------------------------

class mxfp4_base_seq extends uvm_sequence #(blk_pair_item);
  `uvm_object_utils(mxfp4_base_seq)

  function new(string name = "mxfp4_base_seq");
    super.new(name);
  endfunction

  // scaled_exp = sa + sb - 256 を満たす (sa, sb)。0xFF (NaN) は避ける。
  static function void split_scale(input int sexp, output bit [7:0] sa, output bit [7:0] sb);
    int sum;
    sum = sexp + 256;
    if (sum < 0)          begin sa = 8'd0;   sb = 8'd0;         end
    else if (sum <= 254)  begin sa = 8'(sum); sb = 8'd0;        end
    else                  begin sa = 8'd254; sb = 8'(sum - 254); end
  endfunction

  // 全要素が同じコードのブロックペアを投入する
  protected task send_uniform(input bit [7:0] sa, input bit [7:0] sb,
                              input bit [3:0] ca, input bit [3:0] cb,
                              input bit f, input bit l);
    bit [3:0] ea [K], eb [K];
    foreach (ea[i]) begin
      ea[i] = ca;
      eb[i] = cb;
    end
    send_elems(sa, sb, ea, eb, f, l);
  endtask

  // 要素配列を直接与える
  protected task send_elems(input bit [7:0] sa, input bit [7:0] sb,
                            input bit [3:0] ea [K], input bit [3:0] eb [K],
                            input bit f, input bit l);
    blk_pair_item tr;
    tr = blk_pair_item::type_id::create("tr");
    start_item(tr);
    tr.set_blocks(sa, sb, ea, eb);
    tr.first = f;
    tr.last  = l;
    finish_item(tr);
  endtask

  // 要素 idx のみ非ゼロのブロックペア
  protected task send_single(input bit [7:0] sa, input bit [7:0] sb,
                             input int idx, input bit [3:0] ca, input bit [3:0] cb,
                             input bit f, input bit l);
    bit [3:0] ea [K], eb [K];
    foreach (ea[i]) begin
      ea[i] = (i == idx) ? ca : 4'h0;
      eb[i] = (i == idx) ? cb : 4'h0;
    end
    send_elems(sa, sb, ea, eb, f, l);
  endtask
endclass

// -----------------------------------------------------------------------------
// D1: e2m1_decode 全 16 コード (9.3 節 D1)
//   b 側を +1.0 (code 0010) に固定し、a 側に全 16 コードを与える。
//   SoP4 = dec2(a) x dec2(+1.0) = dec2(a) x 2 が 2.1 節の表と一致すれば
//   デコードが正しい (スコアボードの SoP4 整数照合で判定する)。
// -----------------------------------------------------------------------------
class d1_decode_seq extends mxfp4_base_seq;
  `uvm_object_utils(d1_decode_seq)

  function new(string name = "d1_decode_seq");
    super.new(name);
  endfunction

  task body();
    for (int c = 0; c < 16; c++)
      send_single(8'd127, 8'd127, 0, 4'(c), 4'b0010, 1'b1, 1'b1);
  endtask
endclass

// -----------------------------------------------------------------------------
// D2: elem_mul + reduce_tree の境界 (9.3 節 D2)
//   全ゼロ / 全 +6x+6 (SoP4 = +4608) / 全 -6x+6 (-4608) / 単一要素のみ非ゼロ
// -----------------------------------------------------------------------------
class d2_mul_seq extends mxfp4_base_seq;
  `uvm_object_utils(d2_mul_seq)

  function new(string name = "d2_mul_seq");
    super.new(name);
  endfunction

  task body();
    send_uniform(8'd127, 8'd127, 4'b0000, 4'b0000, 1'b1, 1'b1);   // 全ゼロ
    send_uniform(8'd127, 8'd127, 4'b0111, 4'b0111, 1'b1, 1'b1);   // +6 x +6 = +4608
    send_uniform(8'd127, 8'd127, 4'b1111, 4'b0111, 1'b1, 1'b1);   // -6 x +6 = -4608
    for (int i = 0; i < K; i += 7)                                // 単一要素のみ
      send_single(8'd127, 8'd127, i, 4'b0111, 4'b0111, 1'b1, 1'b1);
  endtask
endclass

// -----------------------------------------------------------------------------
// D3: scale_add / NaN と scale 境界 (9.3 節 D3)
// -----------------------------------------------------------------------------
class d3_scale_seq extends mxfp4_base_seq;
  `uvm_object_utils(d3_scale_seq)

  function new(string name = "d3_scale_seq");
    super.new(name);
  endfunction

  task body();
    // NaN スケール (a 側 / b 側 / 両側)
    send_uniform(8'hFF, 8'd127, 4'b0010, 4'b0010, 1'b1, 1'b1);
    send_uniform(8'd127, 8'hFF, 4'b0010, 4'b0010, 1'b1, 1'b1);
    send_uniform(8'hFF, 8'hFF, 4'b0010, 4'b0010, 1'b1, 1'b1);
    // scale 境界 0x00 / 0xFE
    send_uniform(8'h00, 8'h00, 4'b0111, 4'b0111, 1'b1, 1'b1);
    send_uniform(8'hFE, 8'h00, 4'b0111, 4'b0111, 1'b1, 1'b1);
    send_uniform(8'h00, 8'hFE, 4'b0111, 4'b0111, 1'b1, 1'b1);
    send_uniform(8'hFE, 8'hFE, 4'b0010, 4'b0010, 1'b1, 1'b1);
    // 列の途中に NaN が混ざるケース (2.4 節の伝播)
    send_uniform(8'd127, 8'd127, 4'b0010, 4'b0010, 1'b1, 1'b0);
    send_uniform(8'hFF,  8'd127, 4'b0010, 4'b0010, 1'b0, 1'b0);
    send_uniform(8'd127, 8'd127, 4'b0010, 4'b0010, 1'b0, 1'b1);
  endtask
endclass

// -----------------------------------------------------------------------------
// D4: first/last と KBLK = 1 / 2 / 3 の累積 (付録A A.4.4、9.3 節 D4)
//   付録の骨格に scale の制約を足した (スケールが偶発的に NaN / 範囲外へ振れると
//   累積そのものを見なくなるため。判定はリファレンス照合なのでどちらでも通る)。
// -----------------------------------------------------------------------------
class d4_acc_seq extends mxfp4_base_seq;
  `uvm_object_utils(d4_acc_seq)

  int unsigned kblk = 3;             // KBLK = 1 / 2 / 3 を掃引

  function new(string name = "d4_acc_seq");
    super.new(name);
  endfunction

  task body();
    blk_pair_item tr;
    for (int k = 0; k < kblk; k++) begin
      tr = blk_pair_item::type_id::create("tr");
      start_item(tr);
      if (!tr.randomize() with {
        a_scale inside {[8'd120 : 8'd134]};
        b_scale inside {[8'd120 : 8'd134]};
        first == (k == 0);            // 先頭で acc 初期化
        last  == (k == kblk - 1);     // 末尾で結果確定
      }) `uvm_error("D4", "randomize failed")
      finish_item(tr);
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// R1: スケール固定 127 のランダムブロック、SoP4 整数照合 (9.3 節 R1)
// -----------------------------------------------------------------------------
class r1_rand_seq extends mxfp4_base_seq;
  `uvm_object_utils(r1_rand_seq)

  int unsigned n = 1000;

  function new(string name = "r1_rand_seq");
    super.new(name);
  endfunction

  task body();
    blk_pair_item tr;
    repeat (n) begin
      tr = blk_pair_item::type_id::create("tr");
      start_item(tr);
      if (!tr.randomize() with {
        a_scale == 8'd127;
        b_scale == 8'd127;
        first   == 1'b1;
        last    == 1'b1;
      }) `uvm_error("R1", "randomize failed")
      finish_item(tr);
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// R2a: scaled_exp を -120..+110 に制約した累積 (付録A A.4.5、9.3 節 R2a)
//   付録の骨格から c_pack を外した以外は同じ制約 (Issue #1167 の回避)。
//   列長を 1..4 で振り、first/last をシーケンス側で決める。
// -----------------------------------------------------------------------------
class r2a_scaled_exp_seq extends mxfp4_base_seq;
  `uvm_object_utils(r2a_scaled_exp_seq)

  int unsigned n = 200;              // 内積列の本数

  function new(string name = "r2a_scaled_exp_seq");
    super.new(name);
  endfunction

  task body();
    blk_pair_item tr;
    int len;
    repeat (n) begin
      len = $urandom_range(1, 4);
      for (int j = 0; j < len; j++) begin
        tr = blk_pair_item::type_id::create("tr");
        start_item(tr);
        // scaled_exp = sa + sb - 256 (4.5 節) を -120..+110 に制約
        if (!tr.randomize() with {
          a_scale inside {[8'd7 : 8'd247]};
          b_scale inside {[8'd7 : 8'd247]};
          (int'(a_scale) + int'(b_scale) - 256) inside {[-120 : 110]};
          a_scale != 8'hFF; b_scale != 8'hFF;   // NaN は本テストで除外
          first == (j == 0);
          last  == (j == len - 1);
        }) `uvm_error("R2A", "randomize failed")
        finish_item(tr);
      end
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// R2b: オーバーフロー -> ±Inf 飽和 (9.3 節 R2b)
// -----------------------------------------------------------------------------
class r2b_ovf_seq extends mxfp4_base_seq;
  `uvm_object_utils(r2b_ovf_seq)

  function new(string name = "r2b_ovf_seq");
    super.new(name);
  endfunction

  task body();
    bit [7:0] sa, sb;
    for (int s = 0; s < 2; s++) begin
      for (int sexp = 200; sexp <= 252; sexp += 13) begin
        split_scale(sexp, sa, sb);
        // a 側の符号で ±Inf の両極性を踏む
        send_uniform(sa, sb, s ? 4'b1111 : 4'b0111, 4'b0111, 1'b1, 1'b1);
      end
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// R2c: アンダーフロー -> FTZ ±0 (符号保持) (9.3 節 R2c)
// -----------------------------------------------------------------------------
class r2c_uf_seq extends mxfp4_base_seq;
  `uvm_object_utils(r2c_uf_seq)

  function new(string name = "r2c_uf_seq");
    super.new(name);
  endfunction

  task body();
    bit [7:0] sa, sb;
    for (int s = 0; s < 2; s++) begin
      for (int sexp = -256; sexp <= -200; sexp += 13) begin
        split_scale(sexp, sa, sb);
        send_uniform(sa, sb, s ? 4'b1111 : 4'b0111, 4'b0111, 1'b1, 1'b1);
      end
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// R2d: 境界近傍の指数遷移 (9.3 節 R2d)
//   全要素 +6 x +6 -> SoP4 = 4608 = 2^12 + 2^9 なので p = 12。
//   e_conv = p + 127 + scaled_exp が 0/1/2 および 253/254/255 近傍になる
//   scaled_exp を選ぶ。最後に累積の丸め繰り上がりで指数が 1 上がる列を流す。
// -----------------------------------------------------------------------------
class r2d_bound_seq extends mxfp4_base_seq;
  `uvm_object_utils(r2d_bound_seq)

  function new(string name = "r2d_bound_seq");
    super.new(name);
  endfunction

  task body();
    bit [7:0] sa, sb;
    int p, sexp;
    p = 12;

    for (int target = -2; target <= 3; target++) begin
      sexp = target - 127 - p;
      if (sexp >= -256) begin
        split_scale(sexp, sa, sb);
        send_uniform(sa, sb, 4'b0111, 4'b0111, 1'b1, 1'b1);
      end
    end
    for (int target = 252; target <= 256; target++) begin
      sexp = target - 127 - p;
      if (sexp <= 252) begin
        split_scale(sexp, sa, sb);
        send_uniform(sa, sb, 4'b0111, 4'b0111, 1'b1, 1'b1);
      end
    end

    // 累積で丸め繰り上がりが指数を 1 上げるケース:
    // 大きい項に、その ulp の半分ちょうどより上の項を足す
    for (int d = 20; d <= 26; d++) begin
      split_scale(0, sa, sb);
      send_uniform(sa, sb, 4'b0111, 4'b0111, 1'b1, 1'b0);
      split_scale(-d, sa, sb);
      send_uniform(sa, sb, 4'b0111, 4'b0111, 1'b0, 1'b1);
    end
  endtask
endclass

// -----------------------------------------------------------------------------
// E1: 全ゼロブロック -> +0 (9.3 節 E1)
// -----------------------------------------------------------------------------
class e1_allzero_seq extends mxfp4_base_seq;
  `uvm_object_utils(e1_allzero_seq)

  function new(string name = "e1_allzero_seq");
    super.new(name);
  endfunction

  task body();
    send_uniform(8'd127, 8'd127, 4'b0000, 4'b0000, 1'b1, 1'b1);
    // 全ゼロスケール (0x00) の全ゼロブロックも +0
    send_uniform(8'h00, 8'h00, 4'b0000, 4'b0000, 1'b1, 1'b1);
    // 3 ブロック列すべて全ゼロ
    send_uniform(8'd127, 8'd127, 4'b0000, 4'b0000, 1'b1, 1'b0);
    send_uniform(8'd127, 8'd127, 4'b0000, 4'b0000, 1'b0, 1'b0);
    send_uniform(8'd127, 8'd127, 4'b0000, 4'b0000, 1'b0, 1'b1);
  endtask
endclass

// -----------------------------------------------------------------------------
// E2: 相殺 (9.3 節 E2)
//   ブロック内で SoP4 = 0 になる配置と、ブロック間の完全相殺。
// -----------------------------------------------------------------------------
class e2_cancel_seq extends mxfp4_base_seq;
  `uvm_object_utils(e2_cancel_seq)

  function new(string name = "e2_cancel_seq");
    super.new(name);
  endfunction

  task body();
    bit [3:0] ea [K], eb [K];

    // ブロック内 SoP4 = 0 (+6 と -6 のペア)
    foreach (ea[i]) begin
      ea[i] = (i % 2 == 0) ? 4'b0111 : 4'b1111;
      eb[i] = 4'b0111;
    end
    send_elems(8'd127, 8'd127, ea, eb, 1'b1, 1'b1);

    // ブロック間の完全相殺: +X と -X を連続投入 -> +0 (RNE)
    send_uniform(8'd127, 8'd127, 4'b0111, 4'b0111, 1'b1, 1'b0);
    send_uniform(8'd127, 8'd127, 4'b1111, 4'b0111, 1'b0, 1'b1);
  endtask
endclass
