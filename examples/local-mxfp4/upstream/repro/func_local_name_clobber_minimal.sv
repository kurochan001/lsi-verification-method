// -----------------------------------------------------------------------------
// func_local_name_clobber_minimal
//
//   automatic function のローカル変数が、同じ綴りを持つ「呼び出し元 task の
//   for ループ変数」を上書きする。
//
//   構図 (tb_bdp_flow で実際に起きている形):
//     task outer()   : for (int s = 0; s < N; s++) { inner(4); }  <- この s が壊れる
//       task inner() : 時間を消費しながら leaf_s() を呼ぶ
//         function leaf_s() : int s;                              <- 同じ綴り
//
//   壊れるのは「同じ綴り 's' を使う 2 つ目以降の文脈」で、しかも各呼び出しの
//   最初の反復 (s=0) だけ。s には leaf_s() のローカル s の値がそのまま現れる。
//   A は 1 回目だけ無傷で 2 回目以降が壊れ、D は A が先に走っているぶん
//   1 回目から壊れる (A と D の順序を入れ替えると、壊れる側も入れ替わる)。
//
//   条件を 1 つずつ外した対照を同じ実行の中に並べてある:
//     B = ループ変数の綴りだけ変える       -> 無傷
//     C = 関数側ローカルの綴りだけ変える   -> 無傷
//     D = 関数を package から module へ移す -> 同じく壊れる (スコープは無関係)
//     E = 中間 task から時間制御を外す     -> 無傷
//     F = A とまったく同じループを fork...join を通したあとに回す
//
//   対照 (Verilator 5.048) : 18 チェックすべて PASS
//   sukimasim 0.9.9.2:
//     2026-08-13 11:00 ビルド : A の call #2 以降と D の全呼び出しが FAIL
//     2026-08-13 14:07 ビルド : A〜E は PASS になったが **F は 3/3 で FAIL**
//                               (#1204 の部分修正。fork を通る経路が残っていた)
//     2026-08-13 18:01 ビルド : F を含む 18 チェックすべて PASS (#1204 修正・close)。
//                               実 TB (tb_bdp_flow) の `si` 回避策も撤去済み
//
//   LRM: §12.7.1 (for の初期化部で宣言したループ変数は暗黙の begin-end ブロックを
//                 作り、automatic lifetime で「そのループに閉じたスコープ」を持つ。
//                 "Thus, other parallel loops cannot inadvertently affect the
//                  loop control variable.")
//        §6.21   (automatic な task/function 内の変数は local in scope で
//                 lifetime of the call。呼び出しごとに固有)
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

package p_leaf;
  // ローカル変数の綴りが 's'
  function automatic int leaf_s(input int x);
    int s;
    s = 0;
    for (int i = 0; i < 4; i++) s += (x + 1) * (i + 7);
    return s;
  endfunction

  // まったく同じ処理でローカル変数の綴りだけ 'q'
  function automatic int leaf_q(input int x);
    int q;
    q = 0;
    for (int i = 0; i < 4; i++) q += (x + 1) * (i + 7);
    return q;
  endfunction
endpackage

module tb_func_local_clobber;

  import p_leaf::*;

  localparam int N_ITER = 20;
  localparam int N_CALL = 3;

  logic clk;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // package 版とまったく同じ関数を module スコープにも置く
  function automatic int leaf_s_local(input int x);
    int s;
    s = 0;
    for (int i = 0; i < 4; i++) s += (x + 1) * (i + 7);
    return s;
  endfunction

  int checks;
  int errors;
  int sink;

  // ---------------------------------------------------------------------------
  // 中間の automatic task。時間を消費しながら function を呼ぶ。
  // ---------------------------------------------------------------------------
  task automatic inner_pkg_s(input int k);
    for (int j = 0; j < k; j++) begin
      sink = leaf_s(j);
      @(negedge clk);
    end
  endtask

  task automatic inner_pkg_q(input int k);
    for (int j = 0; j < k; j++) begin
      sink = leaf_q(j);
      @(negedge clk);
    end
  endtask

  task automatic inner_local_s(input int k);
    for (int j = 0; j < k; j++) begin
      sink = leaf_s_local(j);
      @(negedge clk);
    end
  endtask

  task automatic inner_pkg_s_nowait(input int k);
    for (int j = 0; j < k; j++) sink = leaf_s(j);
  endtask

  // ---------------------------------------------------------------------------
  // A: 壊れるケース。ループ変数 's' と function のローカル 's' が同じ綴り。
  // ---------------------------------------------------------------------------
  task automatic case_a(input int call_no, output int bad);
    int seen;
    bad = 0;
    for (int s = 0; s < N_ITER; s++) begin
      seen = s;
      inner_pkg_s(4);
      if (s !== seen) begin
        bad++;
        if (bad <= 2)
          $display("       A#%0d: iteration %0d came back as %0d", call_no, seen, s);
      end
    end
  endtask

  // B (対照): ループ変数の綴りだけ 'si' にする。他は A と同一。
  task automatic case_b(input int call_no, output int bad);
    int seen;
    bad = 0;
    for (int si = 0; si < N_ITER; si++) begin
      seen = si;
      inner_pkg_s(4);
      if (si !== seen) bad++;
    end
  endtask

  // C (対照): function 側ローカルの綴りだけ 'q' にする。他は A と同一。
  task automatic case_c(input int call_no, output int bad);
    int seen;
    bad = 0;
    for (int s = 0; s < N_ITER; s++) begin
      seen = s;
      inner_pkg_q(4);
      if (s !== seen) bad++;
    end
  endtask

  // D: 同じ関数を package でなく module スコープに置く。A と同じく壊れる。
  task automatic case_d(input int call_no, output int bad);
    int seen;
    bad = 0;
    for (int s = 0; s < N_ITER; s++) begin
      seen = s;
      inner_local_s(4);
      if (s !== seen) begin
        bad++;
        if (bad <= 2)
          $display("       D#%0d: iteration %0d came back as %0d", call_no, seen, s);
      end
    end
  endtask

  // F: A とまったく同じループを、fork...join を 1 回通したあとに回す。
  //    2026-08-13 の修正で A〜E は通るようになったが、この経路は残っている。
  task automatic with_fork(input int n);
    fork
      begin : only_branch
        for (int s = 0; s < n; s++) inner_pkg_s(4);
      end
    join
  endtask

  // E (対照): 中間 task から時間消費を外す。他は A と同一。
  task automatic case_e(input int call_no, output int bad);
    int seen;
    bad = 0;
    for (int s = 0; s < N_ITER; s++) begin
      seen = s;
      inner_pkg_s_nowait(4);
      if (s !== seen) bad++;
    end
  endtask

  task automatic report(input string tag, input int call_no, input int bad);
    checks++;
    if (bad != 0) begin
      errors++;
      $display("[FAIL] %-40s call #%0d : %0d/%0d iteration(s) corrupted",
               tag, call_no, bad, N_ITER);
    end else begin
      $display("[ ok ] %-40s call #%0d", tag, call_no);
    end
  endtask

  int bad;

  initial begin
    checks = 0;
    errors = 0;
    sink   = 0;
    repeat (2) @(negedge clk);

    for (int c = 1; c <= N_CALL; c++) begin
      case_a(c, bad); report("A: loop var 's', pkg local 's'", c, bad);
    end
    for (int c = 1; c <= N_CALL; c++) begin
      case_b(c, bad); report("B: loop var 'si'      (control)", c, bad);
    end
    for (int c = 1; c <= N_CALL; c++) begin
      case_c(c, bad); report("C: pkg local 'q'      (control)", c, bad);
    end
    for (int c = 1; c <= N_CALL; c++) begin
      case_d(c, bad); report("D: module-local func, local 's'", c, bad);
    end
    for (int c = 1; c <= N_CALL; c++) begin
      case_e(c, bad); report("E: no time control    (control)", c, bad);
    end

    // F: fork...join を 1 回通してから、A とまったく同じループを回す
    with_fork(2);
    for (int c = 1; c <= N_CALL; c++) begin
      case_a(c, bad); report("F: the A loop after a fork...join", c, bad);
    end

    $display("=====================================");
    $display(" func_local_name_clobber_minimal : %0d checks, %0d failures",
             checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
