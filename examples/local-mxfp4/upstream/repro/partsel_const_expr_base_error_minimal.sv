// -----------------------------------------------------------------------------
// sukimasim Issue #1324 の最小再現 (自己チェック型)
//
//   症状: 手続き代入の左辺がインデックス付き部分選択で、そのベースが
//         **定数「式」** (リテラルでも変数でもない、`W*K-1` のような
//         コンパイル時に決まる式) のとき、誤った実行時エラーが出る。
//
//         [ERROR] Assignment failed: Range select assignment:
//                 High index must be an integer
//
//         **メッセージは 2 重に誤っている**:
//           - 代入は失敗していない。書いた値はそのまま読み戻せる (ケース B / F)。
//           - High index は整数である。`W*K-1` は localparam から成る
//             定数整数式で、同じ値のリテラル (255) を書けばエラーは出ない。
//
//   引き金はベースの書き方だけ。同じビットを指していても:
//     - リテラルのベース `f[255 -: 32]`      -> エラーなし (ケース A)
//     - 変数のベース     `f[idx -: 32]`      -> エラーなし (ケース C)
//     - 範囲形           `f[255:224]`        -> エラーなし (ケース D)
//     - 読み側は定数式ベースでもエラーなし               (ケース G)
//     - **定数式のベースを左辺に書いたときだけ**出る     (ケース B / F)
//   `+:` と `-:` の両方で出る。
//
//   期待動作: IEEE 1800-2023 §11.5.1 は
//     「The *msb_base_expr* and *lsb_base_expr* shall be integer expressions,
//      and the *width_expr* shall be a positive constant integer expression.」
//     と定めており、ベースは整数**式**でよい (実行時に変わってもよいとまで
//     書かれている)。さらに
//     「an indexed part-select is a constant part-select if its base is a
//      constant value as well as its width」
//     とあり、定数式ベースはリテラルベースと同じ扱いになる。
//     対照の Verilator 5.050 は 7 ケースすべてエラーも警告も出さない。
//
//   影響: **ログが汚れるだけでなく、本物のエラーが埋もれる。**
//         `W*i +: W` のような書き方は配列を packed に畳むときの定型なので、
//         規模のある TB では大量に出る (本プロジェクトの UVM env では
//         1 ブロックにつき 1 件出ていた)。
//         しかも **この `[ERROR]` は終了ステータスに反映されない** —
//         下の実行例のとおり exit code は 0 で、`TEST PASSED` も印字される。
//         CI が exit code だけを見ていると気付けない (#940 と同系統)。
//
//   実行: sukimasim -top tb_partsel_const_expr_base repro/partsel_const_expr_base_error_minimal.sv
//   合格条件: **`[ERROR]` が 1 件も出ないこと。** 値の照合 7 件は
//         現状の sukimasim でも通る (代入自体は成立しているため)。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_partsel_const_expr_base;

  localparam int K = 8;
  localparam int W = 32;

  logic [W*K-1:0] f;
  int             idx;

  int checks = 0, errors = 0;

  task automatic chk(input string name, input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %-46s got=%08h exp=%08h", name, got, exp);
    end else begin
      $display("[ ok ] %-46s = %08h", name, got);
    end
  endtask

  initial begin
    idx = W*K-1;

    // 対照: リテラルのベース
    f = '0; f[255 -: 32]   = 32'hA1A1A1A1;
    chk("A  f[255 -: 32]      literal base   [control]", f[255:224], 32'hA1A1A1A1);

    // 本題: 定数式のベース (-:)
    f = '0; f[W*K-1 -: W]  = 32'hA2A2A2A2;
    chk("B  f[W*K-1 -: W]     constant-expression base", f[255:224], 32'hA2A2A2A2);

    // 対照: 変数のベース (実行時に変わり得る形)
    f = '0; f[idx -: 32]   = 32'hA3A3A3A3;
    chk("C  f[idx -: 32]      variable base  [control]", f[255:224], 32'hA3A3A3A3);

    // 対照: 範囲形
    f = '0; f[255:224]     = 32'hA4A4A4A4;
    chk("D  f[255:224]        range form     [control]", f[255:224], 32'hA4A4A4A4);

    // 対照: リテラルのベース (+:)
    f = '0; f[224 +: 32]   = 32'hA5A5A5A5;
    chk("E  f[224 +: 32]      literal base +: [control]", f[255:224], 32'hA5A5A5A5);

    // 本題: 定数式のベース (+:)
    f = '0; f[W*(K-1) +: W] = 32'hA6A6A6A6;
    chk("F  f[W*(K-1) +: W]   constant-expression base +:", f[255:224], 32'hA6A6A6A6);

    // 対照: 読み側は定数式ベースでもエラーなし
    f = '0; f[255:224]     = 32'hA7A7A7A7;
    chk("G  read f[W*K-1 -: W]              [control]", f[W*K-1 -: W], 32'hA7A7A7A7);

    $display("=====================================");
    $display(" partsel_const_expr_base_error : %0d checks, %0d errors", checks, errors);
    $display(" NOTE: the defect is the spurious [ERROR] lines above, not these checks.");
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
