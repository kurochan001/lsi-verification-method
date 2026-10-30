// -----------------------------------------------------------------------------
// tb_gradual_uf
//   gradual underflow (デノーマル出力) の検証。仕様書 6.3 節の発展課題 /
//   11 章 段階 7。
//
//   FTZ 版 (GRADUAL_UF = 0) と gradual 版 (GRADUAL_UF = 1) を並べて同じ入力を
//   与え、それぞれのリファレンスとビット一致することを確認する。FTZ 版が
//   既定のまま変わっていないことも同時に押さえられる
//   (仕様書 11 章 段階 7「導入時は統合パスとのビット一致回帰を必須とする」)。
//
//   検証の要点:
//     G1 加算器単体。アンダーフロー境界 (2^-126 近傍) を狙ったランダム。
//        デノーマル化を丸めの後に置くと二重丸めで 1ulp ずれるので、
//        ここが一致するかどうかで順序の正しさが判定できる。
//     G2 加算器単体。デノーマル入力どうし / デノーマル + 正規数。
//        加算器の指数比較は仮数が [1, 2) にあることを前提にしているので、
//        mxfp4_bdp と同じくデノーマルは正規化してから渡す (指数は負になる)。
//     G3 BDP のブロック列。scaled_exp をデノーマル域に置いて累積させる。
//        gradual 版では acc 側の DAZ を外してあるので、デノーマルを跨いだ
//        累積が積み上がって正規最小へ復帰する経路も通る。
//     G4 境界の直接テスト (最小デノーマル / 正規最小への繰り上がり /
//        2^-150 のタイ)。期待値はビットパターンで直接与える。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_gradual_uf;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  // ---------------------------------------------------------------------------
  // クロック / リセット
  // ---------------------------------------------------------------------------
  logic clk;
  logic rst_n;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // ---------------------------------------------------------------------------
  // DUT 1: 加算器コア (FTZ 版 / gradual 版)
  // ---------------------------------------------------------------------------
  logic                     a_sign, b_sign;
  logic signed [IEXP_W-1:0] a_exp, b_exp;
  logic [SIGNIF_W-1:0]      a_sig, b_sig;

  logic                     rf_sign, rf_zero, rf_covf;
  logic signed [IEXP_W-1:0] rf_exp;
  logic [SIGNIF_W-1:0]      rf_sig;

  logic                     rg_sign, rg_zero, rg_covf;
  logic signed [IEXP_W-1:0] rg_exp;
  logic [SIGNIF_W-1:0]      rg_sig;

  mxfp4_fp32_add_core #(.GRADUAL_UF(1'b0)) add_ftz (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(rf_sign), .r_exp(rf_exp), .r_sig(rf_sig),
    .r_carry_ovf(rf_covf), .r_zero(rf_zero)
  );

  mxfp4_fp32_add_core #(.GRADUAL_UF(1'b1)) add_grd (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(rg_sign), .r_exp(rg_exp), .r_sig(rg_sig),
    .r_carry_ovf(rg_covf), .r_zero(rg_zero)
  );

  // ---------------------------------------------------------------------------
  // DUT 2: BDP (FTZ 版 / gradual 版)
  // ---------------------------------------------------------------------------
  logic               in_valid, first, last;
  logic [BLOCK_W-1:0] a_block, b_block;
  logic               ov_ftz, ov_grd;
  logic [31:0]        res_ftz, res_grd;

  mxfp4_bdp #(.GRADUAL_UF(1'b0)) bdp_ftz (
    .clk             (clk),
    .rst_n           (rst_n),
    .in_valid        (in_valid),
    .in_ready        (),
    .a_block         (a_block),
    .b_block         (b_block),
    .first           (first),
    .last            (last),
    .out_valid       (ov_ftz),
    .out_ready       (1'b1),
    .result          (res_ftz),
    .sop4_dbg        (),
    .sop_valid_dbg   (),
    .exp_internal_dbg(),
    .exp_valid_dbg   (),
    .gradual_uf_dbg  ()
  );

  mxfp4_bdp #(.GRADUAL_UF(1'b1)) bdp_grd (
    .clk             (clk),
    .rst_n           (rst_n),
    .in_valid        (in_valid),
    .in_ready        (),
    .a_block         (a_block),
    .b_block         (b_block),
    .first           (first),
    .last            (last),
    .out_valid       (ov_grd),
    .out_ready       (1'b1),
    .result          (res_grd),
    .sop4_dbg        (),
    .sop_valid_dbg   (),
    .exp_internal_dbg(),
    .exp_valid_dbg   (),
    .gradual_uf_dbg  ()
  );

  // ---------------------------------------------------------------------------
  // 集計
  // ---------------------------------------------------------------------------
  int checks;
  int errors;
  int n_denorm_add;    // 加算器が実際にデノーマルを返した回数
  int n_denorm_bdp;    // BDP がデノーマルを出した回数
  int n_ftz_zero;      // 同じ入力で FTZ 版がゼロに潰した回数

  task automatic chk(input string name, input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      if (errors <= 20)
        $display("[FAIL] %s : got=%h exp=%h", name, got, exp);
    end
  endtask

  // ---------------------------------------------------------------------------
  // 内部形式 <-> FP32
  // ---------------------------------------------------------------------------
  // mxfp4_bdp の pack_fp32 と同じ規約
  function automatic logic [31:0] pack(input logic sign,
                                       input logic signed [IEXP_W-1:0] iexp,
                                       input logic [SIGNIF_W-1:0] sig,
                                       input bit gradual);
    if (iexp >= $signed(IEXP_W'(255)))       return {sign, 8'hFF, 23'd0};
    else if (gradual && !sig[SIGNIF_W-1])    return {sign, 8'h00, sig[22:0]};
    else if (iexp <= $signed(IEXP_W'(0)))    return {sign, 31'd0};
    else                                     return {sign, iexp[7:0], sig[22:0]};
  endfunction

  // 仮数 23bit の先頭ゼロ数 (mxfp4_bdp の acc_lz と同じ)
  function automatic int lz23(input logic [22:0] f);
    for (int i = 22; i >= 0; i--) if (f[i]) return 22 - i;
    return 22;
  endfunction

  // FP32 -> (sign, exp, sig)。gradual ではデノーマルを正規化して渡す
  // (mxfp4_bdp が加算器へ渡すときと同じ形)。
  task automatic drive_operands(input logic [31:0] x, input logic [31:0] y,
                                input bit gradual);
    logic dx, dy;
    int   lx, ly;
    dx = gradual && (x[30:23] == 8'h00) && (x[22:0] != 23'd0);
    dy = gradual && (y[30:23] == 8'h00) && (y[22:0] != 23'd0);
    lx = lz23(x[22:0]);
    ly = lz23(y[22:0]);
    a_sign = x[31];
    a_exp  = dx ? IEXP_W'(-lx) : $signed({3'b000, x[30:23]});
    a_sig  = dx ? SIGNIF_W'({1'b0, x[22:0]} << (lx + 1)) : {1'b1, x[22:0]};
    b_sign = y[31];
    b_exp  = dy ? IEXP_W'(-ly) : $signed({3'b000, y[30:23]});
    b_sig  = dy ? SIGNIF_W'({1'b0, y[22:0]} << (ly + 1)) : {1'b1, y[22:0]};
    #1;
  endtask

  // ---------------------------------------------------------------------------
  // G1 / G2: 加算器単体
  // ---------------------------------------------------------------------------
  task automatic add_pair(input string name, input logic [31:0] x, input logic [31:0] y);
    logic [31:0] got_f, got_g;

    // FTZ 版 (DAZ なので入力デノーマルはゼロ扱い。リファレンスも同じ規約)
    drive_operands(x, y, 1'b0);
    got_f = rf_zero ? 32'h0000_0000 : pack(rf_sign, rf_exp, rf_sig, 1'b0);
    if (x[30:23] == 8'h00 && y[30:23] == 8'h00)      got_f = 32'h0000_0000;
    else if (x[30:23] == 8'h00)                      got_f = y;
    else if (y[30:23] == 8'h00)                      got_f = x;
    chk($sformatf("%s ftz", name), got_f, ref_fp32_add_fp32_ex(x, y, 1'b0));

    // gradual 版
    drive_operands(x, y, 1'b1);
    got_g = rg_zero ? 32'h0000_0000 : pack(rg_sign, rg_exp, rg_sig, 1'b1);
    if (x[30:0] == 31'd0 && y[30:0] == 31'd0)        got_g = 32'h0000_0000;
    else if (x[30:0] == 31'd0)                       got_g = y;
    else if (y[30:0] == 31'd0)                       got_g = x;
    chk($sformatf("%s grd", name), got_g, ref_fp32_add_fp32_ex(x, y, 1'b1));

    if (got_g[30:23] == 8'h00 && got_g[22:0] != 23'd0) begin
      n_denorm_add++;
      if (got_f[30:0] == 31'd0) n_ftz_zero++;
    end
  endtask

  function automatic logic [31:0] rand_fp32(input int emin, input int emax);
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'($urandom_range(emin, emax));
    f[22:0]  = 23'($urandom);
    return f;
  endfunction

  function automatic logic [31:0] rand_denorm();
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'h00;
    f[22:0]  = 23'($urandom_range(1, 23'h7FFFFF));
    return f;
  endfunction

  task automatic test_g1(input int n_iter);
    logic [31:0] x, y;
    int e;
    $display("--- G1: adder, underflow boundary (%0d pairs) ---", n_iter);
    for (int t = 0; t < n_iter; t++) begin
      // 指数を 2^-126 近傍 (指数フィールド 1..30) に寄せて、実効減算で
      // デノーマル域へ落ちるケースを大量に踏ませる
      e = $urandom_range(1, 30);
      x = rand_fp32(e, e + 2);
      y = rand_fp32(e, e + 2);
      add_pair("G1", x, y);
    end
  endtask

  task automatic test_g2(input int n_iter);
    logic [31:0] x, y;
    $display("--- G2: adder, denormal operands (%0d pairs) ---", n_iter);
    for (int t = 0; t < n_iter; t++) begin
      case ($urandom_range(0, 2))
        0: begin x = rand_denorm();      y = rand_denorm();      end
        1: begin x = rand_denorm();      y = rand_fp32(1, 5);    end
        2: begin x = rand_fp32(1, 5);    y = rand_denorm();      end
        default: begin x = rand_denorm(); y = rand_denorm();     end
      endcase
      add_pair("G2", x, y);
    end
  endtask

  // ---------------------------------------------------------------------------
  // G3 / G4: BDP のブロック列
  // ---------------------------------------------------------------------------
  function automatic logic [135:0] mk_block(input logic [7:0] scale, input logic [3:0] e [32]);
    logic [127:0] el;
    for (int i = 0; i < 32; i++) el[4*i +: 4] = e[i];
    return {scale, el};
  endfunction

  function automatic logic [135:0] mk_rand(input logic [7:0] scale);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = 4'($urandom_range(0, 15));
    return mk_block(scale, e);
  endfunction

  function automatic logic [135:0] mk_single(input logic [7:0] scale, input int idx,
                                             input logic [3:0] code);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = (i == idx) ? code : 4'h0;
    return mk_block(scale, e);
  endfunction

  // sa + sb = sum となる (sa, sb) を作る
  task automatic split_sum(input int sum, output logic [7:0] sa, output logic [7:0] sb);
    if (sum <= 254) begin sa = 8'(sum);  sb = 8'd0;          end
    else            begin sa = 8'd254;   sb = 8'(sum - 254); end
  endtask

  task automatic run_series(input logic [135:0] a [], input logic [135:0] b []);
    int n;
    n = a.size();
    for (int j = 0; j < n; j++) begin
      @(negedge clk);
      in_valid = 1'b1;
      a_block  = a[j];
      b_block  = b[j];
      first    = (j == 0);
      last     = (j == n-1);
    end
    @(negedge clk);
    in_valid = 1'b0;
    first    = 1'b0;
    last     = 1'b0;
    repeat (LAT - 1) @(posedge clk);
    #1;
    checks++;
    if (!ov_ftz || !ov_grd) begin
      errors++;
      $display("[FAIL] out_valid not asserted at LAT=%0d", LAT);
    end
  endtask

  task automatic check_series(input string name,
                              input logic [135:0] a [], input logic [135:0] b []);
    logic [31:0] ef, eg;
    run_series(a, b);
    ef = ref_dot_series_ex(a, b, 1'b0);
    eg = ref_dot_series_ex(a, b, 1'b1);
    if ((res_ftz !== ef || res_grd !== eg) && errors < 4) begin
      $display("  [dbg] kblk=%0d", a.size());
      for (int j = 0; j < a.size(); j++)
        $display("    j=%0d sa=%0d sb=%0d sop4=%0d sexp=%0d", j,
                 a[j][135:128], b[j][135:128], ref_sop4(a[j], b[j]),
                 int'(a[j][135:128]) + int'(b[j][135:128]) - 256);
    end
    chk($sformatf("%s ftz", name), res_ftz, ef);
    chk($sformatf("%s grd", name), res_grd, eg);
    if (res_grd[30:23] == 8'h00 && res_grd[22:0] != 23'd0) begin
      n_denorm_bdp++;
      if (res_ftz[30:0] == 31'd0) n_ftz_zero++;
    end
  endtask

  task automatic test_g3(input int n_iter);
    logic [135:0] a [], b [];
    logic [7:0] sa, sb;
    int kblk, sum;
    $display("--- G3: BDP series in the denormal range (%0d series) ---", n_iter);
    for (int t = 0; t < n_iter; t++) begin
      kblk = $urandom_range(1, 6);
      a = new[kblk];
      b = new[kblk];
      for (int j = 0; j < kblk; j++) begin
        // 値 = SoP4 x 2^(sa+sb-256)。SoP4 は高々 2^12.2 なので、
        // sa+sb を 100〜135 に置くと結果がデノーマル域 (2^-149..2^-126) を跨ぐ。
        sum = $urandom_range(100, 135);
        split_sum(sum, sa, sb);
        a[j] = mk_rand(sa);
        b[j] = mk_rand(sb);
      end
      check_series("G3", a, b);
    end
  endtask

  task automatic test_g4();
    logic [135:0] a [], b [];
    $display("--- G4: denormal boundary, direct ---");
    a = new[1];
    b = new[1];

    // 要素 0 だけ +0.5 x +1.0 -> prod4 = 1 x 2 = 2、SoP4 = 2
    //   値 = 2 x 2^(sa+sb-256) = 2^(sa+sb-255)
    // sa+sb = 106 -> 2^-149 = 最小デノーマル 0x00000001
    a[0] = mk_single(8'd106, 0, 4'b0001);
    b[0] = mk_single(8'd000, 0, 4'b0010);
    run_series(a, b);
    chk("G4 min denormal (grd)", res_grd, 32'h0000_0001);
    chk("G4 min denormal (ftz)", res_ftz, 32'h0000_0000);

    // sa+sb = 105 -> 2^-150。RNE のタイで偶数側 (= 0) へ
    a[0] = mk_single(8'd105, 0, 4'b0001);
    b[0] = mk_single(8'd000, 0, 4'b0010);
    run_series(a, b);
    chk("G4 half-ulp tie (grd)", res_grd, 32'h0000_0000);

    // 要素 0 が +1.0 x +1.0 -> SoP4 = 4、sa+sb = 104 -> 4 x 2^-152 = 2^-150
    //   タイだが仮数 LSB が 0 なので 0 へ
    a[0] = mk_single(8'd104, 0, 4'b0010);
    b[0] = mk_single(8'd000, 0, 4'b0010);
    run_series(a, b);
    chk("G4 tie via SoP4=4 (grd)", res_grd, 32'h0000_0000);

    // sa+sb = 107 -> 2^-148 = 0x00000002
    a[0] = mk_single(8'd107, 0, 4'b0001);
    b[0] = mk_single(8'd000, 0, 4'b0010);
    run_series(a, b);
    chk("G4 2 ulp denormal (grd)", res_grd, 32'h0000_0002);

    // 全要素 +6 x +6 -> SoP4 = 4608 = 2^9 x 9
    //   sa+sb = 121 -> 4608 x 2^-135 。指数は -135 + 12 = -123 で正規域
    a[0] = mk_block(8'd121, '{32{4'b0111}});
    b[0] = mk_block(8'd000, '{32{4'b0111}});
    run_series(a, b);
    chk("G4 normal range (grd = ftz)", res_grd, res_ftz);

    // デノーマルから正規最小へ積み上がる列。
    //   1 ブロックあたり 2^-149 を足し込むのを 2^23 回…は現実的でないので、
    //   大きめの刻み (2^-127) を 2 回足して 2^-126 (正規最小) を作る。
    //   値 = 2 x 2^(sa+sb-256) = 2^-127 -> sa+sb = 128
    a = new[2];
    b = new[2];
    for (int j = 0; j < 2; j++) begin
      a[j] = mk_single(8'd128, 0, 4'b0001);
      b[j] = mk_single(8'd000, 0, 4'b0010);
    end
    run_series(a, b);
    chk("G4 climb to min normal (grd)", res_grd, 32'h0080_0000);
    // FTZ 版は 1 ブロック目の 2^-127 をその場でゼロに潰すので積み上がらない
    chk("G4 climb to min normal (ftz)", res_ftz, 32'h0000_0000);

    // 上と同じだがブロック数 1 -> 2^-127 はデノーマル (0x00400000)
    a = new[1];
    b = new[1];
    a[0] = mk_single(8'd128, 0, 4'b0001);
    b[0] = mk_single(8'd000, 0, 4'b0010);
    run_series(a, b);
    chk("G4 half of min normal (grd)", res_grd, 32'h0040_0000);
    chk("G4 half of min normal (ftz)", res_ftz, 32'h0000_0000);
  endtask

  int n_iter;

  initial begin
    if (!$value$plusargs("N_GUF=%d", n_iter)) n_iter = 20000;

    checks       = 0;
    errors       = 0;
    n_denorm_add = 0;
    n_denorm_bdp = 0;
    n_ftz_zero   = 0;

    rst_n    = 1'b0;
    in_valid = 1'b0;
    a_block  = '0;
    b_block  = '0;
    first    = 1'b0;
    last     = 1'b0;
    a_sign   = 1'b0; a_exp = '0; a_sig = '0;
    b_sign   = 1'b0; b_exp = '0; b_sig = '0;
    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    test_g4();
    test_g1(n_iter);
    test_g2(n_iter);
    test_g3(n_iter / 20);

    // 非 vacuous: デノーマル出力が実際に発生していること
    checks++;
    if (n_denorm_add == 0) begin
      errors++;
      $display("[FAIL] adder never produced a denormal; test is vacuous");
    end
    checks++;
    if (n_denorm_bdp == 0) begin
      errors++;
      $display("[FAIL] BDP never produced a denormal; test is vacuous");
    end

    $display("=====================================");
    $display(" tb_gradual_uf : %0d checks, %0d errors", checks, errors);
    $display("   denormal results: adder=%0d  bdp=%0d  (FTZ flushed %0d of them)",
             n_denorm_add, n_denorm_bdp, n_ftz_zero);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

endmodule
