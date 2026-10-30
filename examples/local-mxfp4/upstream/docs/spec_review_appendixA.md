# 付録A(UVM ベース検証仕様) レビュー結果

| 項目 | 内容 |
|---|---|
| 宛先 | ブロックスケール MXFP4 演算器 仕様書作成チーム |
| 発信 | RTL 実装・検証担当 |
| 対象文書 | `docs/appendixA/mxfp4_appendixA_uvm.md` |
| 日付 | 2026-08-10 (初版) / 2026-08-21 (第 3 版、5 節に追記) |
| 対象リビジョン | 実装 commit `ef722d4` |
| 検証環境 | Verilator 5.050 / sukimasim 0.9.9.2 (2026-08-20 ビルド) |

本文(Rev.1.3)との整合は良好で、信号名・シナリオ ID・数値規約・観測ポート名はすべて実装と
一致していました。これまでの指摘 (B2 の RAW ハザード、C1/C7 の段分離、`$past` の中間信号規約、
R2f、6.5 節の方針 3) も正しく織り込まれています。

骨格コードを機械抽出し、sukimasim の UVM モードで実際に動かしました。**A.12.3 の V1〜V3 段階は
完走**します。指摘は 4 件 (うち 1 件は本文とコードの不整合) と、V4 段階で観測した事象 1 件です。

---

## 1. 検証結果

### 1.1 実行環境の確立

`sukimasim --enable-uvm` で UVM モードに入ります。同梱ライブラリは
`1800.2-2020.3.1/src/`(A.1.3 が指定する UVM-2020 系)です。

| 段階 (A.12.3) | 内容 | 結果 |
|---|---|---|
| V1 | 空の `uvm_test` を `run_test()` で完走 | **完走** (全 phase + レポートサマリ) |
| V2 | `mxfp4_base_test` の build〜end_of_elaboration | **完走** |
| V3 | `d4_acc_seq` で driver / sequencer / monitor 経路 | **完走** (UVM_ERROR 0) |

抽出したのは A.4.1 / A.4.4 / A.4.5 / A.5.1 / A.5.2 / A.6.2 / A.8.1 / A.8.2 の 8 ブロックで、
未定義要素 (`bdp_result_item` / `env_config` / `bdp_if` / `bdp_agent` 等) だけをスタブで補い、
**付録のコードは無修正**で使いました。`uvm_active_passive_enum` / `uvm_tlm_analysis_fifo` /
`uvm_sequencer#(T)::type_id` はいずれも問題なく解決します。

`blk_pair_item` に `post_randomize()` のセルフチェック (A.12.3 の推奨手法) を足して
`c_pack` の充足を確認したところ、V3 の範囲では違反ゼロでした。

---

## 2. 指摘

### A-1. A.5.1 driver が本文の要求 (隙間なし連続投入) を満たしていない

#### 該当箇所

A.5.1 の本文は次のように書いています。

> 要点は内積列を隙間なく連続投入できることで、**これは B2 の RAW ハザード検出に必須**である。

しかし直後の骨格コードは item ごとに `in_valid` を落とします。

```systemverilog
    vif.cb.in_valid <= 1'b1;
    ...
    @(vif.cb);
    vif.cb.in_valid <= 1'b0;   // 連続投入時は drop せず次 item へ直結する変種を使用
    seq_item_port.item_done();
```

さらに `do @(vif.cb); while (vif.cb.in_ready !== 1'b1);` は `do`-`while` なので
**`in_ready` が既に 1 でも必ず 1 サイクル消費**します。結果として最短でも 1 item あたり
2 サイクルかかり、隙間が空きます。

#### 問題

**これは A1 (桁上げ時の sticky) と同じ構図**です。本文にだけ書かれた要求はコードを写経する
実装者から漏れます。しかも B2 は「acc の読み書きが 1 サイクルに閉じているか」を検出する唯一の
経路なので、隙間が空いた driver では **RAW ハザードがあっても回帰が緑のまま通ってしまいます**。

実装側のプレーン SV 版 (`tb_top` の Driver) は隙間なく連続投入する構成にしてあり、これが
B2 の検出に効いています。

#### 修正案

コメントで変種に言及するのではなく、連続投入版そのものを骨格に載せることを提案します。

```systemverilog
task bdp_driver::run_phase(uvm_phase phase);
  blk_pair_item tr;
  @(posedge vif.clk); wait (vif.rst_n);
  forever begin
    // 次 item が無ければ valid を落とす。あれば落とさずに直結する
    if (!seq_item_port.has_do_available()) begin
      vif.cb.in_valid <= 1'b0;
      wait (seq_item_port.has_do_available());
    end
    seq_item_port.get_next_item(tr);
    while (vif.cb.in_ready !== 1'b1) @(vif.cb);   // 既に 1 なら待たない
    vif.cb.in_valid <= 1'b1;
    vif.cb.a_block  <= tr.a_block;
    vif.cb.b_block  <= tr.b_block;
    vif.cb.first    <= tr.first;
    vif.cb.last     <= tr.last;
    @(vif.cb);
    seq_item_port.item_done();
  end
endtask
```

あわせて A.5.1 の本文に「この driver で B2 が検出できることを、EX1 で acc を読む版の RTL に
差し替えて確認する (ミューテーションテスト)」と一文を添えると、要求が形骸化しません。

### A-2. A.8.1 の drain time が LAT に足りない

#### 該当箇所

```systemverilog
  function void end_of_elaboration_phase(uvm_phase phase);
    // LAT = 6 の後追い結果取りこぼし防止のドレインタイム
    uvm_phase run_ph = uvm_run_phase::get();
    run_ph.phase_done.set_drain_time(this, 20);
  endfunction
```

#### 問題

`set_drain_time` の第 2 引数は**シミュレーション時間**であってサイクル数ではありません。
A.11.2 の VCS 起動例が `-timescale=1ns/1ps` なので 1 単位 = 1 ns、`20` は **20 ns** です。

一方 LAT = 6 は 6 サイクルであり、クロック周期 10 ns なら **60 ns** 必要です。20 ns では
最後の内積列の `out_valid` が立つ前に run_phase が終了し、**scoreboard が最終結果を
取りこぼします**。A.11.3 の本文が「drain time(例: LAT + 余裕)」と書いているのは正しいので、
コードだけがそれを満たしていません。

#### 修正案

クロック周期に依存しない形にするのが安全です。

```systemverilog
  function void end_of_elaboration_phase(uvm_phase phase);
    uvm_phase run_ph = uvm_run_phase::get();
    // LAT = 6 サイクル + 余裕。CLK_PERIOD は config から受け取る
    run_ph.phase_done.set_drain_time(this, (mxfp4_pkg::LAT + 4) * cfg.clk_period);
  endfunction
```

`env_config` に `clk_period`(time 型) を追加し、A.2.3 の表にも 1 行足す形を提案します。

### A-3. A.11 に sukimasim の起動方法がない

A.11 は Xcelium / VCS の起動オプションを表と実例で示していますが、**sukimasim の項がありません**。
A.12.3 が sukimasim でのデバッグを V1〜V7 の段階に分けて計画している以上、起動コマンドが
無いと着手できません。

今回の検証で確立した内容を提案します。

| 項目 | sukimasim |
|---|---|
| UVM 有効化 | `--enable-uvm` (uvm_macros.svh を自動 include) |
| 外部 UVM ライブラリ | `+incdir+<path>/src +define+UVM_NO_DPI <path>/src/uvm_pkg.sv` |
| テスト選択 | `+UVM_TESTNAME=<test>` (共通) |
| verbosity | `+UVM_VERBOSITY=<lvl>` (共通) |
| シード | (要確認。`--seed-sweep` は code-coverage 用) |
| タイムアウト | `--max-time 1us` / `--wall-timeout <sec>` (CI 用のハング防止) |
| UVM デバッグ | `--uvm-config-db-trace` / `--uvm-phase-trace` |

```text
sukimasim --enable-uvm -top hw_top +UVM_TESTNAME=mxfp4_bdp_acc_test \
  +UVM_VERBOSITY=UVM_MEDIUM --max-time 1us -f files.f
```

**`--enable-uvm` を付けないと `uvm_info 等のマクロが未解決のままパースエラーになる**ので、
A.12.3 の V1 で最初に踏みます。表に明記しておく価値があります。

### A-4 (軽微). A.6.2 の骨格が `in_fifo` を使っていない

`in_fifo` を宣言しながら `run_phase` では `out_fifo` からしか取り出していません。
「集約モデルは省略」と明記されているので意図的と理解しましたが、節のタイトルが
「in-order 比較」なので、`in_fifo.get()` で first..last を集める骨格まで載せる方が
節の主旨と合います (集約の中身は省略のままでよいと思います)。

---

## 3. V4 (制約付きランダム) で観測した事象

A.12.3 の V4 に相当する段階で、`blk_pair_item` の randomize がシミュレータによって
挙動を変えることを確認しました。**付録の記述に誤りがあるという指摘ではなく、V4 で実際に
踏むことになる事象の先出し**です。

| 条件 | Verilator 5.048 | sukimasim |
|---|---|---|
| `c_pack` のみ (inline 制約なし) | 成功 | **成功** |
| scale のみ + r2a の inline 制約 | 成功 | **成功** |
| `c_pack` + r2a の inline 制約 (= A.4.5 の実際の形) | 成功 (100/100) | **ソルバタイムアウト** |

sukimasim は `Constraint solver timeout after ~2100 attempts (hard constraints only,
treating as failure)` を出して randomize が失敗します。

その後さらに切り分けたところ、要素数は無関係で、**幅 69bit 以上の rand 変数に part-select の
等式制約があり、かつ in-line 制約が付いたとき**に限って失敗すると判明しました
(幅 68bit まで / part-select が下位 64bit ワード内 / in-line 制約なし のいずれかなら解ける)。
sukimasim へ **Issue #1167** として最小再現つきで報告済みです
(`repro/constraint_partselect_minimal.sv`)。

### 提案: block を非 rand にして `post_randomize()` でパックする

制約ソルバに 136bit の等式を解かせる必然性はありません。

```systemverilog
class blk_pair_item extends uvm_sequence_item;
  bit [135:0] a_block, b_block;          // rand を外す (ソルバの対象にしない)
  rand bit [7:0] a_scale, b_scale;
  rand bit [3:0] a_elem[32], b_elem[32];
  rand bit first, last;
  ...
  function void post_randomize();
    a_block[135:128] = a_scale;
    b_block[135:128] = b_scale;
    foreach (a_elem[i]) a_block[4*i +: 4] = a_elem[i];
    foreach (b_elem[i]) b_block[4*i +: 4] = b_elem[i];
  endfunction
endclass
```

こうすると制約は `a_scale` / `b_scale` / `a_elem` / `b_elem` の範囲・分布だけになり、
`c_pack` が不要になります。プレーン SV 版 (9 章) も同じ考え方で、ブロックは
`mk_block()` 関数で組み立てて制約ソルバを通していません。

この形にすると、Issue #1167 の条件 (幅の広い rand 変数への part-select 等式制約) が
そもそも発生しません。`post_randomize()` の基本動作は両シミュレータで確認済みです。

なお 64 要素規模での `post_randomize()` については、こちらの試作で Verilator と sukimasim が
別々の不整合を示しており、**試作コード側の誤りの可能性も残ります**。断定できる段階ではないので、
V4 の着手時に商用シミュレータを交えた三者比較で切り分けることを提案します。

---

## 4. まとめ

| # | 節 | 内容 | 重み |
|---|---|---|---|
| A-1 | A.5.1 | driver が本文の要求 (隙間なし連続投入) を満たさない。B2 が検出できなくなる | 高 |
| A-2 | A.8.1 | drain time 20 が LAT = 6 に足りない (60 ns 必要)。最終結果を取りこぼす | 中 |
| A-3 | A.11 | sukimasim の起動方法がない。`--enable-uvm` 必須 | 中 |
| A-4 | A.6.2 | `in_fifo` を使わない骨格 (節タイトルと不整合) | 低 |

V4 で踏む制約ソルバの事象は第 3 節にまとめました。`c_pack` を `post_randomize()` へ移す案を
併せて提案します。

### 再現手順

1. 付録の ```systemverilog ブロックから 8 ブロックを抽出し、未定義要素をスタブで補う
2. `sukimasim --enable-uvm -top hw_top +UVM_TESTNAME=<test> --max-time 5us <file>`
3. `blk_pair_item::post_randomize()` に制約充足のセルフチェックを入れて V4 を観測する

---

## 5. 追記 (2026-08-10): UVM 版 env を実装した結果

付録A の env を実際に実装しました (`tb/uvm/`)。骨格レビュー (1〜4 節) の指摘は
すべて実装に反映しています。ここでは**実装して初めて分かった付録への追加指摘**と、
**sukimasim 側で新たに見つかった不具合**を分けて報告します。

### 5.1 付録への追加指摘

| # | 節 | 内容 | 重み |
|---|---|---|---|
| A-5 | A.3.1 | `bdp_if` の clocking block が `cb` 1 つしかない。monitor が `cb` の output (`a_block` 等) を読むと driver が最後に書いた値が返り、DUT が受け取った値の観測にならない。入力専用の `cb_mon` を分けるべき | 中 |
| A-6 | A.3.1 | 信号表に `out_ready` がない。RTL は 3.3 節の ready 拡張を実装しているので、インターフェースにも収容が要る (env 側で 1 固定にするにせよ、信号がないと接続できない) | 中 |
| A-7 | A.5.1 | driver の隙間なし連続投入は、`item_done()` を転送エッジより**前**に呼ぶのが要点。A-1 の修正案は `item_done()` をエッジの後に置いており、同一時刻で `has_do_available()` を評価すると結局 1 サイクル空く | 中 |
| A-8 | A.5.1 | `wait (seq_item_port.has_do_available())` は式中に変数が現れないため、処理系によっては再評価されずデッドロックし得る。クロック単位のポーリングか `try_next_item()` を使う形を骨格に載せるべき | 中 |
| A-9 | A.5.2 | monitor を `fork mon_in(); mon_out(); mon_sop(); mon_exp(); join` と 4 プロセスに割る必要はない。段分離の要点は analysis port とトランザクションを段ごとに分けることで、1 プロセスで 4 系統をサンプルしても段分離は保たれる。プロセスを増やすとイベント待ちの取りこぼしを踏みやすい | 低 |

実装は A-5〜A-9 をすべて反映した形にしてあります (`tb/uvm/bdp_agent.svh` の
コメントに対応を明記)。

### 5.2 sukimasim 側で新たに見つかった不具合

env を立ち上げる過程で、付録のコードでも実装のコードでもなく**シミュレータ側**の
問題を 6 件切り分けました。いずれも Verilator 5.048 を対照に取っています。

| # | 症状 | 再現 | 状態 |
|---|---|---|---|
| #1170 | クラスメソッド内からクラスプロパティへ部分代入すると、直前の全体代入以降 最初の 1 回しか反映されない | `repro/class_prop_partsel_minimal.sv` | **修正済み** (残っていた `this.` 明示形は #1206 として切り出され、これも修正済み) |
| #1171 | 同じクロックを `@(posedge vif.clk)` で待つプロセスが並走していると、`@(vif.cb)` の待ちが最初の 1 回で止まる | `repro/clocking_event_minimal.sv` | **修正済み** |
| #1172 | `--enable-uvm` を付けるだけで、UVM を使っていない既存 TB (`tb_top`) の演算結果が X になる | `repro/uvm_mode_encoder_x_minimal.sv` | **修正済み** |
| #1174 | 設計側の信号と同名のクラスメンバは、ソルバが書いた値が `finish_item()` のサスペンドを跨いで「最初の item の値」へ巻き戻る | 単体再現なし。実 env で確認 | **修正済み** |
| #1176 | run phase の objection が 0 になった瞬間に、`run_test()` を呼ぶモジュール自身の静的プロセスが kill され、設計側の continuous assign も凍結する | `repro/uvm_objection_drop_teardown_minimal.sv` | **修正済み** |
| #1178 | `--enable-uvm` を付けるだけで、generate ループ内のサブモジュールのポートへ繋いだ genvar 依存の選択が反復ごとに評価されない | `repro/uvm_mode_genvar_port_select_minimal.sv` | **修正済み** |

**追記 (2026-08-13): 6 件すべてが sukimasim 側で修正され、UVM 版 env は
実行可能な uvm_test 12 本すべてが PASS しました** (`0 UVM_ERROR` / mismatch 0、
最長の `mxfp4_bdp_regress_test` で result 278 件 / sop4 435 件の照合)。
上表の「状態」列はこの再測定に合わせて更新してあります。
`#1174` については、実 env で観測していた症状の真因は #1195 (平坦化した
`handle.member` ミラーが、綴りを共有する無関係なオブジェクトのメンバを書く) の方でした。
これも修正済みで、当初 env 側に入れていた回避策 (`first` / `last` を制約でなく
`randomize()` 直後の代入で与える) は撤去し、**付録A どおりの制約形に戻して**
同一結果になることを確認しています。

#1176 に対しては、クロック生成をサブモジュール (`hw_clkgen`) へ追い出す回避策を
入れてあります (サブモジュールに属するプロセスは kill されません)。修正後もこの形は
そのままにしています。**付録A 側への提案としては残ります** — A.2.3 に
「クロック生成はトップに置かずサブモジュールへ」という注記を入れておくと、
drain time の設計 (A-2) と合わせて他の環境が同じ穴に落ちずに済みます。

### 5.3 A.11 への追記 (A-3 の続き)

sukimasim の起動方法として、本実装では次を使っています。

```text
make sim-uvm UVM_TEST=mxfp4_bdp_acc_test
# 展開すると
sukimasim --enable-uvm -assert -top hw_top +UVM_TESTNAME=<test> \
  +UVM_VERBOSITY=UVM_LOW --max-time 50us --wall-timeout 1800 \
  +incdir+tb/uvm <rtl> <sva> <ref> tb/uvm/mxfp4_uvm_if.sv \
  tb/uvm/mxfp4_uvm_pkg.sv tb/uvm/hw_top.sv
```

`+incdir+tb/uvm` が要ります (パッケージを `` `include `` で分割しているため)。
また **DUT はトップごとに 1 つに絞る**必要があります。BDP・エンコーダ・加算器を
同じトップに載せると組合せ評価が収束せず (`COMB_EVAL fallback` /
`Combinational settle truncated`)、駆動していない DUT の X が観測ポートへ漏れます。
A.2.1 の図11 は単体レベルを 1 つの env として描いていますが、トップは分けるのが
実務的です。

---

## 6. 追記 (2026-08-21): 送付時点の状態

初版 (2026-08-10) と 5 節の追記 (2026-08-13) の後、シミュレータ側の修正が進んだので
送付にあたって現況をまとめ直します。**付録A への指摘 (A-1〜A-9) は初版・追記から
変更ありません。** 以下は状態の確認のみです。

### 6.1 5.2 節に挙げた不具合はすべて解消

6 件すべてが修正され、そこから派生した残件も閉じました。**`repro/` のうち
修正済み Issue に対応する再現ケースはすべて PASS** です
(Verilator 5.050 / sukimasim 2026-08-20 ビルドで実測)。

- #1170 の残件だった `this.` 明示形は **#1206** として切り出され、修正済み。
  その切り分けの過程で **#1207** (メソッド内からクラスプロパティへの部分選択 NBA が
  落ちる) と **#1208** (深さ 2 以上のメンバ連鎖 `a.b.c[hi:lo]` への書き込みが落ちる)
  が分離され、いずれも修正済みです。
- したがって 5.2 節が挙げた「`post_randomize()` のパックはローカル変数を経由する」
  回避策は、**もはや必須ではありません**。ただし本実装はこの形のまま維持しています
  (制約ソルバに 136bit の等式を解かせない、という 3 節の提案そのものは
  シミュレータの不具合とは独立に有効なため)。

### 6.2 uvm_test 12 本を再実測

2026-08-20 ビルドで 12 本すべてを回し直し、**`0 UVM_ERROR` / mismatch 0、
照合件数まで 2026-08-13 の測定と完全に一致**しました
(最長の `mxfp4_bdp_regress_test` で result 278 件 / sop4 435 件)。

### 6.3 3.3 節 ready/FIFO の TB が両シミュレータで一致

長く 4-state 側だけ結果が合っていなかった `tb_bdp_flow` (3.3 節の ready 拡張 +
入力 FIFO を検証する TB) が、**既定 N で 1,257 チェック / 0 errors / 結果 1,250 件と
Verilator に一致**するようになりました。原因は 2 つともシミュレータ側で、
**automatic subroutine のローカル変数・値渡し formal が呼び出しごとの記憶域を
持っていなかった**というものです (IEEE 1800-2023 §6.21 / §13.3.1 / §13.5.1。
sukimasim #1204 / #1205 / #1218 / #1221、いずれも修正済み)。
付録A の記述に関わる問題ではありませんが、**A.12.3 の段階検証で「結果が出てこない」
「値が合わない」に出会ったとき、TB 側の綴りの衝突を疑う前にシミュレータの
automatic 変数の寿命を疑う価値がある**という実例として共有します。

### 6.4 新たに 5 件報告しました (#1319〜#1323、いずれも OPEN)

enc / add_core / GEMM の env を立ち上げる過程で切り分けたものです。
付録A の記述に誤りがあるという指摘ではありませんが、**うち 4 件は
「回帰が緑のまま通ってしまう」形で出る**ので、A.12 の検証手順に関わります。

| # | 内容 | 検証手順への影響 |
|---|---|---|
| #1319 | `+UVM_TESTNAME` の解決が factory registry を経由しない。**存在しない testname でも `UVM_FATAL` にならず正常終了する** | 打ち間違えた回帰が「緑」で通る |
| #1320 | interface の unpacked 配列メンバがポート接続されると書き込みが届かない | DUT が全ゼロを受け取り、**全ゼロ期待値と一致して通る** |
| #1321 | `assign` の左辺がインデックス付き部分選択だとベクタを駆動しない | 観測ポートが X のまま。カバレッジが伸びないことだけが手掛かり |
| #1322 | UVM コンポーネントのタスクで、`if` 内の `for` がローカルへ書いた値が、同じブロックのハンドル経由メソッド呼び出しで失われる | **monitor が全ゼロを配り、スコアボードが vacuous に一致して通る** |
| #1323 | `dist` の重みが無視され、狙ったモードが 1 件も生成されない | `post_randomize()` のセルフチェックは 0 violations を返す |

### 6.4.1 A.12 への提案 — 「通ったこと」を疑う検査を手順に入れる

上の 4 件はいずれも**照合が一致してしまう**形で出ます。原因は共通していて、
**全ゼロの入力は全ゼロの出力と一致し、参照モデルも全ゼロを返す**ためです。
付録A の A.12.3 (段階検証) に、次の 2 つを明示的な合格条件として
書き加えることを提案します。

1. **テストが実際に構築されたことを確認する** (#1319 対策)。
   `uvm_top.print_topology()` か、コンポーネント数の下限チェック。
2. **照合が非 vacuous であることを検査する** (#1320 / #1322 対策)。
   スコアボードに「何を踏んだか」の統計を持たせ、`check_phase` で
   下限を要求する。本実装では次のようにしています。

   | env | 非 vacuous 性の指標 |
   |---|---|
   | enc | クランプ / フラッシュ件数。全ゼロなら 0 になる |
   | add_core | 指数差 1..30 の帯の件数、完全相殺の件数 (どちらも 0 なら失敗) |
   | GEMM | C の非ゼロ要素数 (0 なら失敗)、qNaN 件数 |

   この検査が無いと、上記の不具合はどれも**検出できません**。実際、
   enc env では #1322 のせいで `mismatches=0` のまま丸一日進めてしまい、
   機能カバレッジが伸びないことだけが手掛かりでした。

### 6.5 付録A の env を全レベル実装しました

送付にあたっての現況です。**付録A が挙げている単体レベルの env はすべて実装し、
動作を確認しました。**

| レベル | 節 | シナリオ | トップ | 状態 |
|---|---|---|---|---|
| BDP | A.5〜A.8 | D1〜D4 / R1 / R2a〜R2e / E1 / E2 | `hw_top` | uvm_test 12 本 PASS |
| quant_encoder | A.3.2 | D5 (エンコーダ経由分) / R3 | `hw_enc_top` | 3 本 PASS、`cg_enc` 100% |
| add_core | A.10 | R2f | `hw_add_top` | 2 本 PASS |
| GEMM | A.9 (方式 Y) | E3 | `hw_gemm_top` | 2 本 PASS (C 48 件一致、done サイクル一致) |

A.9.1 の助言どおり、**空の virtual_sequencer は方式 Y の段階から置いてあります**
(`mxfp4_virtual_sequencer`)。いまは gemm_sequencer のハンドルを持つだけですが、
bdp_agent を passive で載せて方式 X へ移す際の接続点になります。

A.9.2 の done サイクル機械照合も実装しました。monitor が start から done までを
計数し、scoreboard が 1 + KBLK + LAT と比較します。あわせて 8.6 節の
「C は done の次サイクル以降に読み出し、次の start まで保持される」規約も
monitor が毎サイクル検査しています。

**A.11 への追加提案 (実測にもとづく運用)**: GEMM レベルは DUT が 16 PE ぶんあるため、
4-state シミュレータでは 1 回の実行に CPU 1,181 秒、3 回の実行では 6,221 秒
(1 時間 45 分) かかりました。付録A のレグレッション運用に
「**GEMM レベルの UVM 実行は X 伝播と規約照合に絞り、量はプレーン SV + 2-state 側で
稼ぐ**」という但し書きを入れておくと、他の環境が「UVM 版で回数を稼ごうとして詰まる」
のを避けられます。

### 6.6 この env がバグ発見装置として働いている点について

初版から通算して、付録A の env とそれに付随する TB の立ち上げから
シミュレータ側の不具合を 21 件切り分けました。内訳は、**UVM 経路から出たもの**が
#1167 (3 節の制約ソルバ) / #1170 / #1171 / #1172 / #1174 / #1175 / #1176 / #1178 /
#1195 / #1206 / #1207 / #1208 / #1319 / #1320 / #1321 / #1322 / #1323 の 17 件、
**プレーン SV の TB (3.3 節 ready/FIFO) から出たもの**が
#1204 / #1205 / #1218 / #1221 の 4 件です
(このうち #1175 / #1195 / #1207 / #1208 / #1218 / #1221 は、こちらが出した報告を
シミュレータ側が切り分ける過程で分離された派生分です)。

A.12.3 の段階検証 (V1〜V4) を「env が動くまでの手順」としてだけでなく
**処理系の切り分け手順**としても読めるようにしておくと、他の環境でも同じ効き方を
すると思われます。具体的には、各段階に「ここで期待どおりにならない場合、
まず Verilator など別処理系で同じ骨格を走らせて差分を取る」という一文を
添えるかたちを提案します。
