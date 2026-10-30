// -----------------------------------------------------------------------------
// sukimasim Issue #1323 の最小再現 (自己チェック型)
//
//   症状: `dist` の重みが無視される。**implication 制約の帰結が、別の制約
//         ブロックでも縛られている変数に触れているとき**に起きる。
//         偏りは両方向に出て、極端な場合はある値が**一度も生成されない**。
//
//   引き金の切り分け (下のケース A〜D がそのまま対照になっている):
//     A: `dist` だけ                                   -> 正しい
//     B: `dist` + implication。帰結が触る変数は他の制約に出てこない -> 正しい
//     C: B の帰結を「c_norm でも縛っている変数」に変える -> **崩れる**
//     D: 実プロジェクトの形 (C をさらに絞ったもの)       -> **崩れて 1 が 0 件になる**
//   C と B の違いは帰結が参照する変数だけで、`dist` も implication の形も同じ。
//
//   期待動作: IEEE 1800-2023 §18.5.4 は dist を
//     「値の集合と、それぞれの相対的な重み」と規定しており、
//     重みは解の**確率分布**を決める。他の制約は解空間を絞るだけで、
//     残った解の中での相対的な重みを変えてはならない。
//     ここでは 4 ケースとも制約は充足可能で、m = 0/1/2 はすべて到達可能。
//     対照の Verilator 5.050 は 4 ケースとも重みどおりの分布になる。
//
//   影響: **黙って検証の穴になる。** dist は「めったに起きない条件を狙って
//         踏ませる」ための道具なので、重みが効かないと狙ったケースが
//         永久に生成されない。エラーも警告も出ず、回帰は緑のまま通る。
//         本プロジェクトでは R2f (加算器単体) の完全相殺モードが
//         `dist { 0 := 70, 1 := 10, 2 := 20 }` の 1 に割り当てられており、
//         200 回まわしても 1 件も出なかった。
//
//   判定: 各ケースで N 回 randomize し、m の出現数が重みから大きく外れて
//         いないかを見る。ばらつきで落ちないよう帯は広めに取ってあり
//         (期待値の 0.5 倍〜1.5 倍)、正しい実装なら十分な余裕で収まる。
//
//   実行: sukimasim -top tb_constraint_dist repro/constraint_dist_ignored_minimal.sv
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_constraint_dist;

  localparam int N = 2000;   // 期待値: m=0 -> 1400、m=1 -> 200、m=2 -> 400

  // ---------------------------------------------------------------------------
  // A (対照): dist だけ
  // ---------------------------------------------------------------------------
  class c_a;
    rand int unsigned m;
    constraint c_mode { m dist { 0 := 70, 1 := 10, 2 := 20 }; }
  endclass

  // ---------------------------------------------------------------------------
  // B (対照): dist + implication。帰結が触る x / y は他の制約に出てこない
  // ---------------------------------------------------------------------------
  class c_b;
    rand bit [7:0]         x, y;
    rand bit signed [10:0] ea, eb;
    rand bit [23:0]        ga, gb;
    rand int unsigned      m;
    constraint c_norm { ga[23] == 1'b1; gb[23] == 1'b1;
                        ea inside {[1:254]}; eb inside {[1:254]}; }
    constraint c_mode {
      m dist { 0 := 70, 1 := 10, 2 := 20 };
      (m == 0) -> (x < y);
      (m == 1) -> (x == y);
    }
  endclass

  // ---------------------------------------------------------------------------
  // B2 (対照): B と同じだが、等式の対象を **C と同じ 24bit** にする。
  //   ga/gb は c_norm に出てこない点だけが C との違い。
  //   「等式が厳しすぎるから重みを満たせない」という説明が成り立たないことを
  //   示すための対照 — 難しさは C と同じで、結果は重みどおりになる。
  // ---------------------------------------------------------------------------
  class c_b2;
    rand bit [23:0]        ua, ub;      // どの制約ブロックにも出てこない
    rand bit signed [10:0] ea, eb;
    rand bit [23:0]        ga, gb;
    rand int unsigned      m;
    constraint c_norm { ga[23] == 1'b1; gb[23] == 1'b1;
                        ea inside {[1:254]}; eb inside {[1:254]}; }
    constraint c_mode {
      m dist { 0 := 70, 1 := 10, 2 := 20 };
      (m == 0) -> (ua < ub);
      (m == 1) -> (ua == ub);
    }
  endclass

  // ---------------------------------------------------------------------------
  // C (本題): B2 と同じ形だが、帰結が c_norm でも縛っている変数に触る
  //   B との違いはここだけ (x/y -> ea/eb, ga/gb)。
  // ---------------------------------------------------------------------------
  class c_c;
    rand bit [7:0]         x, y;
    rand bit signed [10:0] ea, eb;
    rand bit [23:0]        ga, gb;
    rand int unsigned      m;
    constraint c_norm { ga[23] == 1'b1; gb[23] == 1'b1;
                        ea inside {[1:254]}; eb inside {[1:254]}; }
    constraint c_mode {
      m dist { 0 := 70, 1 := 10, 2 := 20 };
      (m == 0) -> (ea < eb);
      (m == 1) -> (ga == gb);
    }
  endclass

  // ---------------------------------------------------------------------------
  // D (本題): 実プロジェクトの addcore_item そのままの形
  //   仕様書 9.3 節 R2f の「同符号 + 指数差 1..30」と「完全相殺」を
  //   dist で振り分けている。
  // ---------------------------------------------------------------------------
  class c_d;
    rand bit               a_sign, b_sign;
    rand bit signed [10:0] a_exp,  b_exp;
    rand bit [23:0]        a_sig,  b_sig;
    rand int unsigned      m;
    constraint c_norm { a_sig[23] == 1'b1; b_sig[23] == 1'b1;
                        a_exp inside {[1:254]}; b_exp inside {[1:254]}; }
    constraint c_mode {
      m dist { 0 := 70, 1 := 10, 2 := 20 };
      (m == 0) -> (a_sign == b_sign && (b_exp - a_exp) inside {[1:30]});
      (m == 1) -> (a_sign != b_sign && a_exp == b_exp && a_sig == b_sig);
    }
  endclass

  int checks = 0, errors = 0;
  int cnt [3];

  // 期待値の 0.5 倍〜1.5 倍に収まっているか
  function automatic void chk_band(input string name, input int got, input int exp);
    checks++;
    if (got < (exp / 2) || got > (exp + exp / 2)) begin
      errors++;
      $display("[FAIL] %-40s m-count=%0d, expected about %0d", name, got, exp);
    end else begin
      $display("[ ok ] %-40s m-count=%0d (about %0d)", name, got, exp);
    end
  endfunction

  function automatic void report(input string name);
    $display("       %-12s counts: 0=%0d 1=%0d 2=%0d (of %0d)", name, cnt[0], cnt[1], cnt[2], N);
    chk_band({name, " m=0 (weight 70)"}, cnt[0], (N * 70) / 100);
    chk_band({name, " m=1 (weight 10)"}, cnt[1], (N * 10) / 100);
    chk_band({name, " m=2 (weight 20)"}, cnt[2], (N * 20) / 100);
  endfunction

  c_a oa; c_b ob; c_b2 ob2; c_c oc; c_d od;

  initial begin
    oa = new(); ob = new(); ob2 = new(); oc = new(); od = new();

    cnt = '{0, 0, 0};
    for (int i = 0; i < N; i++) begin void'(oa.randomize()); if (oa.m < 3) cnt[oa.m]++; end
    report("A dist only [control]");

    cnt = '{0, 0, 0};
    for (int i = 0; i < N; i++) begin void'(ob.randomize()); if (ob.m < 3) cnt[ob.m]++; end
    report("B free vars [control]");

    cnt = '{0, 0, 0};
    for (int i = 0; i < N; i++) begin void'(ob2.randomize()); if (ob2.m < 3) cnt[ob2.m]++; end
    report("B2 24-bit free [control]");

    cnt = '{0, 0, 0};
    for (int i = 0; i < N; i++) begin void'(oc.randomize()); if (oc.m < 3) cnt[oc.m]++; end
    report("C bound vars");

    cnt = '{0, 0, 0};
    for (int i = 0; i < N; i++) begin void'(od.randomize()); if (od.m < 3) cnt[od.m]++; end
    report("D project shape");

    $display("=====================================");
    $display(" constraint_dist_ignored_minimal : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
