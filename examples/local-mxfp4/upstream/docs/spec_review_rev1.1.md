# 設計仕様書 Rev.1.1 レビュー結果

| 項目 | 内容 |
|---|---|
| 宛先 | ブロックスケール MXFP4 演算器 仕様書作成チーム |
| 発信 | RTL 実装・検証担当 |
| 対象文書 | `docs/mxfp4_spec_rev1.1.md` (Rev.1.1, 2026-08-10) |
| 日付 | 2026-08-10 |

Rev.1.1 を精読し、**合意した 11 項目すべての反映を確認した**。さらに約束どおり
5.6 節と 7.3 節の骨格コードを仕様書から機械抽出し、実際にコンパイル・シミュレーションして
リファレンスモデルと突き合わせた。

**結論: 骨格コードのロジックは正しい (260,133 チェック / 不一致 0)。**
ただし**そのままではコンパイルできない**構文上の問題が 2 件残っている (B6 / B7)。
いずれも Rev.1.0 から継続しているもので、こちらが初版フィードバックで報告し損ねていた。
加えて反映漏れが 2 件 (C6 / C7) ある。

---

## 1. 反映確認

| # | 反映先 | 状態 |
|---|---|---|
| B1 | 5.6 節 丸めビット位置 (`norm[26:3]` / `[2]=G [1]=R [0]=S`) | 反映 |
| A1 | 5.6 節 桁上げ時 `norm[0] = norm[0] \| sum[0]` | 反映 |
| — | 5.4 節 28bit フレームのビット割当明記 | 反映 |
| B2 | 3.2 節段表 / 5.5 節 / 図5 キャプション / 5.6 節コメント | 反映 (4 箇所すべて) |
| B3 | 7.2 節場合分け表 / 7.3 節コード (`rm1` / `carry`) | 反映 |
| B4 | 7.3 節 `is_zero` の `unique case` 外出し | 反映 |
| B5 | 9.2 節スライス `a[4*i +: 4]` / 2.3 節前提一文 | 反映 |
| C1 | 9.4 節 covergroup の段別分割 | 反映 (cg_bdp のみ。→ C7) |
| C2 | 9.4 節 `ignore_bins hi` / `bins low` 拡張 | 反映 |
| C3 | 7.4 節 上限クランプ注記 (252 で記載) | 反映 |
| C4 | 6.5 節 方針 3 追加 + 適用条件の書き分け | 反映 |
| C5 | 8.6 節 読み出しタイミング | 反映 |
| R2f | 9.3 節シナリオ + 注 / 11 章段階 3 / 12 章注意 11 | 反映 |
| — | 10 章 運用ノート 5 点 | 反映 (第四点に誤り → C6) |
| — | 改訂履歴 | 反映 |

7.2 節の場合分け表が `010 / 011 / 100` の 3 通りに直っている点、12 章に注意 11
(加算器変更時は R2f 再実行) が追加されている点は、こちらの意図を正確に汲んでいただけた。

## 2. 骨格コードの実機検証

仕様書の ```systemverilog ブロックから 7.3 節 `e2m1_quantize` と 5.6 節
`mxfp4_fp32_add_core` を機械抽出し、モジュール名だけ変えて実行した
(ロジックは 1 文字も変更していない)。

| 対象 | テスト | 結果 |
|---|---|---|
| 7.3 節 `e2m1_quantize` | `e_rel` −5..5 × 代表 frac 11 通り + `is_zero` 11 通り (7.2 節確定表と照合) | 132 / 0 errors |
| 5.6 節 `mxfp4_fp32_add_core` | A1 反例 + 指数差 1..30 の狙い撃ち 60,000 + 一様ランダム 200,000 (R2f 相当) | 260,001 / 0 errors |

- A1 の反例 `0x417C7180 + 0x3F00FC52` は正しく `0x418240A3` を返す。
- B3 の 4 例 (1.5 / 1.75 / 3.0 / 0.75) はすべて 7.2 節の確定表どおり。

**Rev.1.1 の骨格コードは、下記 B6 / B7 を直せば実装にそのまま使える。**

---

## 3. 新規指摘

### B6. 5.6 節 — 骨格コードがそのままではコンパイルできない (Rev.1.0 から継続)

#### 該当箇所

Rev.1.1 の 507 行目と 544 行目。

```systemverilog
  always_comb begin
    a_ge = (a_exp > b_exp) || ...;
    ...
    sh = (exp_diff > 11'sd26) ? 6'd26 : exp_diff[5:0];
    // GRS付き幅へ拡張してから右シフト。押し出しビットのORをstickyへ
    logic [27:0] ext_s; logic [27:0] shifted;    // ← 507 行: 文の後に宣言
    ext_s   = {1'b0, sig_s, 3'b000};
```

```systemverilog
    round_up = g & (rnd | stk | lsb);

    logic [24:0] rounded;                        // ← 544 行: 同上
    rounded = {1'b0, norm[26:3]} + round_up;
```

#### 問題

IEEE 1800-2023 §9.3.1 / A.6.3 の構文は

```
seq_block ::= begin [ : block_identifier ] { block_item_declaration } { statement_or_null } end
```

であり、`block_item_declaration` は**すべて `begin` の直後**に置かなければならない。
文の後に宣言を混ぜることはできない。実際 Verilator は次のエラーで停止する。

```
%Error: spec_fp32_add_core.sv:29:18: syntax error, unexpected IDENTIFIER, expecting "'{"
%Error: spec_fp32_add_core.sv:66:18: syntax error, unexpected IDENTIFIER, expecting "'{"
```

10 章が「手続きブロック内の一時宣言」を検証対象言語機能に挙げているだけに、
その使用例が構文違反になっているのは避けたい。

#### 修正案

宣言を各 `always_comb` の `begin` 直後へ移動する (ロジックの変更は不要)。

```systemverilog
  always_comb begin
+   logic [27:0] ext_s, shifted;
    a_ge = (a_exp > b_exp) || ...;
    ...
-   logic [27:0] ext_s; logic [27:0] shifted;
    ext_s   = {1'b0, sig_s, 3'b000};
```

```systemverilog
  always_comb begin
+   logic [24:0] rounded;
    eff_sub   = (s_l ^ s_s);
    ...
-   logic [24:0] rounded;
    rounded = {1'b0, norm[26:3]} + round_up;
```

この移動だけで抽出コードはコンパイルが通り、上表の 260,001 件を完走する
(実際にこの形で検証した)。

### B7. 5.6 節 — `nlz` のデフォルト代入位置でラッチが推論される

#### 該当箇所

```systemverilog
    if (sum[27]) begin           // 桁上げ: 右シフト1
      norm    = sum >> 1;
      norm[0] = norm[0] | sum[0];
      exp_n   = exp_l + 11'sd1;
    end else begin               // LZCで左詰め
      nlz = 5'd0;                // ← else 側の中でしか代入されない
      for (int i = 26; i >= 0; i--)
        if (sum[i]) begin nlz = 5'd26 - i[4:0]; break; end
      ...
```

#### 問題

`nlz` は `sum[27]` が真のパスで代入されないため、`always_comb` でラッチが推論される。
Verilator は **11 件**の `LATCH` 警告を出す (`nlz` 本体に加え、これに依存する
`lsb` / `g` / `rnd` / `stk` / `round_up` / `rounded` / `r_sign` / `r_exp` / `r_sig` /
`r_carry_ovf` まで芋づる式)。

```
%Warning-LATCH: Latch inferred for signal 'nlz' (not all control paths of
                combinational always assign a value)
```

#### 修正案

`nlz` のデフォルト代入を `if` の前へ出す。**これ 1 行で 11 件の警告がすべて消える**
(実測: 11 件 → 0 件)。

```systemverilog
    // 正規化
+   nlz = 5'd0;
    if (sum[27]) begin
      ...
    end else begin
-     nlz = 5'd0;
      for (int i = 26; i >= 0; i--)
```

### C6. 10 章 — `$past` に関する運用ノートが第 2 版の訂正を反映していない

#### 該当箇所

10 章 運用上の注意 第四点。

> 第四に、SVA の $past(expr, N) は N をパラメータで与えたときの履歴の数え方が
> シミュレータ間で一致しないことがあるため使わず、last の投入数と out_valid の
> 観測数の一致などの計数照合をスコアボード側で行う。

#### 問題

これはこちらの**初版**フィードバックの記述で、第 2 版 (commit `3e92496`) で訂正済みである。
その後の切り分けで原因が特定できたため、現在の記述は事実と異なる。

| 初版の推測 | 実際 (切り分け済み) |
|---|---|
| `number_of_ticks` の数え方が不一致 | **数え方は両シミュレータとも LRM 準拠**。単一信号を渡す限り完全に一致する |
| どのシミュレータが正しいか不明 | **LRM 準拠は Verilator**。sukimasim 0.9.9.2 の不具合 |
| `$past` を使わない | **中間信号を経由すれば使える**。禁止する必要はない |

真の原因は「**`$past` の第 1 引数が式のとき** sukimasim が 1 tick 余分に遅れた値を返す」
ことである。IEEE 1800-2023 §16.9.3 は `expression1` に任意の式を許し、
「*k* 番目の strictly prior なティックでのサンプル値」を返すと規定している。
`bind` の有無・パラメータかリテラルか・covergroup の有無はいずれも無関係と確認済み。
sukimasim へは Issue #1164 として報告し、最小再現を `repro/past_expr_minimal.sv` に置いた。

この記述のまま運用すると、9.5 節に逆向きプロパティ
(`out_valid |-> $past(..., LAT)`) を追加できなくなる。実際には次の形で両シミュレータとも
成立する。

```systemverilog
logic accept_last;
assign accept_last = in_valid && last;      // 式を中間信号へ

property p_ovalid_cause;
  @(posedge clk) disable iff (!rst_n)
    out_valid |-> $past(accept_last, LAT);
endproperty
```

#### 修正案

> 第四に、SVA の `$past` に渡す第 1 引数は式ではなく中間信号にすること。
> `$past(in_valid && last, LAT)` のように式を直接渡すと、処理系によっては
> 1 tick 余分に遅れた値が返る事例がある (IEEE 1800-2023 §16.9.3 は
> `expression1` に任意の式を許し、*k* 番目の strictly prior なティックでの
> サンプル値を返すと規定しているので処理系側の不具合。sukimasim 0.9.9.2 で確認、
> Verilator 5.048 は規定どおり)。`assign` で単一信号にしてから渡せば移植性が保てる。

### C7. 9.4 節 — `cg_enc` に C1 の修正が適用されていない

#### 該当箇所

```systemverilog
covergroup cg_enc @(posedge clk iff enc_valid);
  cp_code: coverpoint mag3_dbg { bins all_codes[] = {[0:7]}; }
  cp_erel: coverpoint e_rel_dbg { ... }
  cp_tie: coverpoint tie_hit_dbg;
endgroup
```

#### 問題 1: サンプルタイミング

`cg_bdp` は段別に 3 分割されたが、`cg_enc` は据え置きになっている。
`e_rel_dbg` / `mag3_dbg` は 7.6 節の stage5 の組合せ出力なので、`enc_valid`
(= `out_valid`、stage5 の**段レジスタ出力**) でサンプルすると 1 サイクル後の
別ブロックの値を拾う。C1 と同じ誤りである。

対応する段の valid (stage5 の組合せが有効なサイクル) でサンプルする必要がある。

#### 問題 2: 配列要素の扱い

`e_rel_dbg` / `mag3_dbg` は 7.6 節の構成上、**要素ごとに 32 本ある**
(`e_rel_dbg[K]` / `mag3_dbg[K]`)。単一の `coverpoint` では 1 要素しか観測できず、
`cp_code` の全 8 コードを埋めるのに 32 倍の試行が要る。

実装では clocking event を持たない covergroup にして、K 要素をループで明示
`sample()` する形を採った。

```systemverilog
covergroup cg_enc;                    // clocking event なし
  cp_code: coverpoint cov_mag3 { bins all_codes[] = {[0:7]}; }
  cp_erel: coverpoint cov_erel { ... }
  cp_tie:  coverpoint cov_tie;
endgroup

always @(posedge clk) begin
  if (rst_n && enc_q_valid) begin     // stage5 の組合せが有効な段
    for (int i = 0; i < K; i++) begin
      cov_mag3 = mag3_dbg[i];
      cov_erel = e_rel_dbg[i];
      cov_tie  = tie_of(e_rel_dbg[i], v_q4[i][22:0], v_q4[i][30:23] == 8'h00);
      cg_enc_i.sample();
    end
  end
end
```

この形で sukimasim 上の `cg_enc` は 100% に到達する。

### C8 (軽微). 4.6 節 / 7.6 節のポート表に `*_dbg` が無い

9.4 節は「SoP4 / exp_internal / e_rel を観測ポート (`*_dbg`) として引き出し、
それぞれに対応する段の valid (`sop_valid_dbg`、`exp_valid_dbg` 等) も併せて引き出す」
と要求しているが、4.6 節の `mxfp4_bdp` トップポート表と 7.6 節のエンコーダポート表には
該当する行が無い。ポート表だけを見て実装すると観測ポートが作られず、9.4 節が実行できない。

両ポート表に観測ポートの行を追加することを提案する (合成時は削除可能である旨も添えると
親切)。

---

## 4. 提案: 完全相殺のバイパスを骨格コードに入れる

5.6 節の注は Rev.1.0 から変わらず

> 完全相殺時(sum 全ゼロ)は正規化をバイパスして +0 を出力する分岐を実装時に追加すること。

としているが、**これは A1 と同じ構図**である。本文にだけ書かれた規定は、骨格コードを
写経する実装者から落ちる。実際 `sum == 0` のとき骨格コードは

- LZC ループがどのビットにもマッチせず `nlz = 0` のまま
- `norm = 0` → `rounded = 0` → `r_sig = 0`

となり、**暗黙 1 を持たない不正な有効仮数**を出力する。呼び出し側が気付かなければ
そのままパックされる。

骨格コードに 1 分岐入れ、あわせて出力ポートに `r_zero` を追加することを提案する。

```systemverilog
  output logic               r_zero        // 完全相殺 (結果 +0)
...
    // 正規化
    nlz = 5'd0;
    if (sum == '0) begin          // 完全相殺: +0 (IEEE 754 RNE の規定)
      norm  = '0;
      exp_n = exp_l;
    end else if (sum[27]) begin
      ...
    end
...
    r_zero = (sum == '0);
```

R2f を段階 3 の完了基準に入れた以上、完全相殺も R2f のダイレクトケースとして
明示しておくと取りこぼしがなくなる (9.3 節 E2 は BDP レベルの相殺なので、
加算器単体の相殺とは別物)。

---

## 5. まとめ

Rev.1.1 は合意項目をすべて正確に反映しており、骨格コードのロジックも実機で確認できた。
Rev.1.2 で扱っていただきたいのは次の 5 件である。

| # | 節 | 内容 | 重み |
|---|---|---|---|
| B6 | 5.6 | 変数宣言位置が構文違反。そのままコンパイルできない | 高 (写経が止まる) |
| B7 | 5.6 | `nlz` のデフォルト代入位置でラッチ推論 (警告 11 件) | 中 |
| C6 | 10 | `$past` の運用ノートが第 2 版の訂正を反映していない | 中 (9.5 節の記述力を落とす) |
| C7 | 9.4 | `cg_enc` にサンプルタイミング分割と配列要素の扱いが未反映 | 中 |
| C8 | 4.6 / 7.6 | ポート表に `*_dbg` と段 valid が無い | 低 |

加えて 5.6 節への完全相殺分岐の追加を提案する (第 4 節)。

### 再現手順

本レビューの骨格コード検証は次の手順で再現できる。

1. 仕様書の ```systemverilog ブロックから `module e2m1_quantize` と
   `module mxfp4_fp32_add_core` を含むものを抽出し、モジュール名を変える
2. B6 の修正 (宣言を `begin` 直後へ移動) を当てる — これをしないとコンパイルできない
3. `tb/mxfp4_ref_pkg.sv` の `ref_quantize_e2m1()` / `ref_fp32_add_fp32()` と照合する
   (前者は 7.2 節の区間表を実数比較で実装したもの、後者は 6.5 節の方針 3)
