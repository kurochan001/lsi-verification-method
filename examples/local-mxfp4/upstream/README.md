> このディレクトリは `kurochan001/mxfp4` の `347edbb8e45454e84945a13c1815e08937feff3f` を取り込んだものです。
> 本リポジトリでの実行方法・修正点・確認範囲は [教材のREADME](../README.md) を参照してください。
> 付録Bを基に追加したFP16／MXFP8の実装は [拡張仕様](../MULTIPRECISION.md) を参照してください。
> 下記の過去の実行結果・Issue状況は、本文に記した確認時点の記録です。

# ブロックスケール MXFP4 演算器

OCP Microscaling Formats (MX) Specification v1.0 に準拠したブロックスケール MXFP4 演算器の
SystemVerilog 実装。設計仕様は [`docs/mxfp4_spec_rev1.3.md`](docs/mxfp4_spec_rev1.3.md)
(実装はこの版に追従済み)。

学習用途と、自作 IEEE 1800-2023 準拠シミュレータ *sukimasim* の検証ターゲット供給という
2 つの目的を持つ。


## 付録A: UVM ベース検証環境 (オプション、BDP 単体レベルは全 PASS)

`tb/uvm/` に仕様書 付録A (`docs/appendixA/mxfp4_appendixA_uvm.md`) の UVM 版 env を
実装した。9 章のプレーン SV 環境 (`tb/tb_top.sv` ほか) が既定で、こちらはオプション。

| ファイル | 内容 |
|---|---|
| `tb/uvm/mxfp4_uvm_if.sv` | `bdp_if` / `enc_if` / `addcore_if` / `gemm_if` (A.3) |
| `tb/uvm/mxfp4_items.svh` | トランザクション (A.4.1 / A.4.2) |
| `tb/uvm/bdp_seq_lib.svh` | D1〜D4 / R1 / R2a〜R2d / E1 / E2 のシーケンス (A.4.3〜A.4.5) |
| `tb/uvm/bdp_agent.svh` | driver / monitor / sequencer / agent (A.5) |
| `tb/uvm/mxfp4_scoreboard.svh` | in-order 比較 (A.6)。`mxfp4_ref_pkg` をプレーン SV 版と共用 |
| `tb/uvm/mxfp4_cov.svh` | 段別カバレッジ subscriber (A.7) |
| `tb/uvm/mxfp4_env.svh` / `mxfp4_test_lib.svh` | env と uvm_test 12 種 (A.8) |
| `tb/uvm/hw_top.sv` | トップ (A.3.3) |

```bash
make sim-uvm     UVM_TEST=mxfp4_bdp_acc_test      # D4 (BDP レベル)
make sim-uvm     UVM_TEST=mxfp4_bdp_regress_test  # 全シーケンス + カバレッジ閉包
make sim-uvm-enc UVM_TEST=mxfp4_enc_regress_test  # エンコーダレベル (D5 / R3)
make sim-uvm-add UVM_TEST=mxfp4_r2f_test          # 加算器単体レベル (R2f)
make sim-uvm-gemm UVM_TEST=mxfp4_e3_identity_test # GEMM レベル (E3)。約 20 分
make sim-uvm-gemm UVM_TEST=mxfp4_e3_test         # 同上 + NaN 伝播。約 1 時間 45 分
```

**2026-08-13 に実行可能な uvm_test 12 本すべてが PASS した** (`0 UVM_ERROR` /
スコアボード mismatch 0)。長くブロッカーだった sukimasim Issue #1178 (generate 内の
ポート接続の genvar 選択) / #1176 (objection drop でのプロセス kill) / #1174 が
シミュレータ側で修正されたことによる。**2026-08-21 に 2026-08-20 09:03 ビルドで
再実測し、12 本ともチェック数まで下表と完全に一致した。**

| test | result / sop4 | test | result / sop4 |
|---|---|---|---|
| `mxfp4_decode_test` | 16 / 16 | `mxfp4_r2b_test` | 10 / 10 |
| `mxfp4_mul_test` | 8 / 8 | `mxfp4_r2c_test` | 10 / 10 |
| `mxfp4_scale_test` | 8 / 10 | `mxfp4_r2d_test` | 18 / 25 |
| `mxfp4_bdp_acc_test` | 3 / 6 | `mxfp4_allzero_test` | 3 / 5 |
| `mxfp4_rand_sop_test` | 100 / 100 | `mxfp4_cancel_test` | 2 / 3 |
| `mxfp4_r2a_test` | 100 / 251 | `mxfp4_bdp_regress_test` | 278 / 435 |

`mxfp4_base_test` / `mxfp4_seq_test` は単体で走らせるものではない (前者はシーケンスを
起動しない基底、後者は `pure virtual` を持つ `virtual class`)。

BDP・エンコーダ・加算器・GEMMの4レベルに、env・agent・test・トップが実装されています。上記12本の表はBDPレベルの過去の実行記録です。本教材の既定リグレッションはプレーンSV版を実行し、このUVM環境の成功は代用しません。

付録A の骨格から変更した点は各ファイル冒頭のコメントに理由付きで書いてある
(隙間なし連続投入、drain time、`post_randomize()` でのパック、clocking block 不使用、
uvm_subscriber 経由のスコアボード接続、クロック生成のサブモジュール化など)。
`first` / `last` を制約でなく代入で与える回避策は 2026-08-13 に撤去し、付録A どおりの
制約形へ戻した (真因だった sukimasim #1195 が修正されたため。撤去の前後で
4 テストのログ全文が完全に同一であることを確認済み)。

## 構成

```
rtl/
  mxfp4_pkg.sv            共通パッケージ (型・構成パラメータの一元配布)
  e2m1_decode.sv          L0: E2M1 -> dec2 (value x2 の整数)
  elem_mul.sv             L1: dec2 同士の要素積 (prod4)
  reduce_tree.sv          L1: 32 項整数加算ツリー (S2/S3 の 2 段)
  scale_add.sv            L1: E8M0 指数合成 (sa + sb - 256)
  mxfp4_i2f.sv            L1: int14 -> 内部拡張 FP32 変換
  mxfp4_fp32_add_core.sv  L1: 統合パス FP32 加算器 (GRS 3bit / RNE)
  mxfp4_bdp.sv            L1: ブロック内積ユニット (6 段パイプ, = PE)
  e2m1_quantize.sv        L0: FP32 相対指数 -> E2M1 コード (RNE)
  amax_tree32.sv          L0: 32 入力 amax トーナメント (2 段パイプ)
  quant_encoder.sv        L0: FP32 x32 -> mxfp4_block_t (5 段パイプ)
  gemm_ctrl_fsm.sv        L2: IDLE/LOAD/COMPUTE/DRAIN 制御 FSM
  mxfp4_gemm_top.sv       L2: 4x4 output-stationary GEMM トップ
  --- 発展課題 (仕様書 11 章 段階 7) ---
  mxfp4_lza.sv               L0: Leading Zero Anticipator (5.7 節)
  mxfp4_fp32_add_nearfar.sv  L1: near/far 二経路 FP32 加算器 (5.7 節)
  mxfp4_fifo.sv              L0: 同期 FIFO (FWFT。3.3 節の ready 拡張用)
  mxfp4_bdp_fifo.sv          L1: 入力 FIFO + BDP のラッパ (3.3 節)

tb/
  mxfp4_ref_pkg.sv        リファレンスモデル (広幅整数による厳密 FP32 加算)
  mxfp4_bdp_sva.sv        SVA (仕様書 9.5 節)。bind で全 BDP インスタンスへ接続
  tb_fp32_add.sv          R2f (加算器単体。任意の FP32 ペアで丸め経路を全域検査)
  tb_mxfp4_bdp.sv         D1-D4 / R1 / R2a-R2e / E1 / E2
  tb_quant_encoder.sv     D5 / R3 / エッジケース / tie_hit_dbg 検査
  tb_mxfp4_gemm_top.sv    E3 (単位行列・ランダム・NaN 伝播・done サイクル照合)
  tb_top.sv               仕様書 9.1 節のクラスベース TB
                          (class / mailbox / 制約付きランダム / covergroup)
  --- 発展課題 ---
  tb_bdp_flow.sv          ready/FIFO のフロー制御 (3.3 節)
  tb_quant_q34.sv         3/4 スケーリング vs Algorithm 1 (7.7 節)
  tb_gradual_uf.sv        gradual underflow vs FTZ (6.3 節)
  tb_nearfar.sv           near/far + LZA vs 統合パス (5.7 節)

docs/
  mxfp4_spec_rev1.3.md    設計仕様書 (最新)
  appendixA/              付録A: UVM ベース検証仕様 (オプション。4レベルを実装済み)
  spec_feedback_rev1.0.md Rev.1.0 へのフィードバック (第 2 版)
  spec_review_rev1.1.md   Rev.1.1 レビュー結果
  spec_review_rev1.2.md   Rev.1.2 確認結果 (指摘なし)
  spec_review_rev1.3.md   Rev.1.3 レビュー (段階 7 の実装から。D1 / E1〜E3)
  spec_review_appendixA.md 付録A レビュー (A-1〜A-4)
repro/
  past_expr_minimal.sv            sukimasim Issue #1164 の最小再現
  constraint_partselect_minimal.sv  sukimasim Issue #1167 の最小再現
  class_prop_this_partsel_minimal.sv  sukimasim Issue #1206 の最小再現
  func_local_name_clobber_minimal.sv  sukimasim Issue #1204 の最小再現
  uvm_testname_factory_bypass_minimal.sv  sukimasim Issue #1319 の最小再現
  if_unpacked_port_name_clash_minimal.sv  sukimasim Issue #1320 の最小再現
  assign_partsel_lhs_minimal.sv           sukimasim Issue #1321 の最小再現
  constraint_dist_ignored_minimal.sv      sukimasim Issue #1323 の最小再現
  partsel_const_expr_base_error_minimal.sv  sukimasim Issue #1324 の最小再現
  uvm_task_local_loop_write_lost_minimal.sv  sukimasim Issue #1322 の最小再現
```

`repro/` はいずれも自己チェック型で、UVM 非依存。Verilator では PASS、sukimasim では
該当項目が FAIL する形にしてあり、sukimasim 側の回帰にそのまま追加できる。
`make repro` で全部回る。**2026-08-21 時点 (バイナリ 2026-08-20 09:03 ビルド) で、
修正済み Issue の再現ケースはすべて PASS** — 最後まで残っていた Issue #1206 が
修正され、既知 FAIL は無くなった。
出力に残る `[FAIL]` 行は OPEN な Issue #1319 / #1320 / #1321 / #1322 / #1323 の分で、これは正常。
`uvm_testname_factory_bypass_minimal.sv` は 5 ケースのうち B / C / D で
「走ってはいけないテストが走ったこと」を `[FAIL]` として刻む作りにしてある。
`if_unpacked_port_name_clash_minimal.sv` は既定 (同綴り) が 3 errors、
`+define+RENAMED` の対照が 0 errors になるのが正しい状態。
`assign_partsel_lhs_minimal.sv` は 7 checks 中 3 errors。

RTL は仕様書 4.6 / 7.6 節の観測ポート (`*_dbg`) を実装しており、テストベンチは
RTL 内部への階層参照を一切持たない。

## ビルドと実行

必要なツール: **Verilator 5.x**（機能カバレッジを取る場合は **sukimasim** も）

```bash
make lint      # RTL + SVA の静的検査
make test      # lint + 全テストベンチをビルドして実行
make clean
```

ランダム試行回数は plusargs で調整できる。

```bash
make sim-add  N_ADD=300000
make sim-bdp  N_R1=100000 N_R2A=20000 N_R2E=200
make sim-enc  N_R3=20000
make sim-gemm N_GEMM=500
make sim-top  N_SERIES=5000 N_ENC=1000
```

発展課題 (仕様書 11 章 段階 7) の回帰:

```bash
make sim-flow   N_FLOW=1000    # 3.3 節 ready/FIFO のフロー制御
make sim-q34    N_Q34=20000    # 7.7 節 3/4 スケーリング
make sim-guf    N_GUF=50000    # 6.3 節 gradual underflow
make sim-nf     N_NF=200000    # 5.7 節 near/far + LZA (加算器単体)
make sim-bdp-nf                # 同上を BDP 全体で (-GUSE_NEARFAR=1)
```

下記は、当時のsukimasimで機能カバレッジ (covergroup) を取得した手順である。本教材のVerilator実行ではこの計測を有効化していない。
4-state 実行なので X 伝播の検査も兼ねる。

```bash
make sim-sukima N_SERIES=100 N_ENC=30
```

### 回帰結果

Verilator 5.050 / 上記の試行回数 (2026-08-21 にクリーンビルドで実測):

| テストベンチ | チェック数 | 結果 |
|---|---:|---|
| `tb_fp32_add` | 660,001 | PASS |
| `tb_mxfp4_bdp` | 478,792 | PASS |
| `tb_quant_encoder` | 80,197 | PASS |
| `tb_mxfp4_gemm_top` | 8,553 | PASS |
| `tb_top` | 7,001 | PASS |
| `tb_bdp_flow` | 4,057 | PASS |
| `tb_quant_q34` | 80,686 | PASS |
| `tb_gradual_uf` | 207,519 | PASS |
| `tb_nearfar` | 2,467,699 | PASS |
| `tb_mxfp4_bdp` (`USE_NEARFAR=1`) | 478,792 | PASS |

合計 4,473,297 チェック / 0 errors。

> Verilator 5.048 での前回値は `tb_nearfar` 2,467,163 / 合計 4,472,761 だった。
> 差の 536 は 5.050 で `$urandom` の系列が変わり、条件付きチェックの命中数が動いたもの。
> 他の 9 本はチェック数まで 5.048 と同一で、いずれの版でも 0 errors。

sukimasim 0.9.9.2 (`-assert +define+MXFP4_COVERAGE`, N_SERIES=100 / N_ENC=30):
SVA 違反なし、機能カバレッジは全 covergroup 100%。

| covergroup | 対象 | カバレッジ |
|---|---|---:|
| `cg_bdp_in` | a/b スケール分布、first x last の全 4 組合せ | 100.00% |
| `cg_bdp_sop` | SoP4 の符号・ゼロ | 100.00% |
| `cg_bdp_exp` | 内部指数の uf / norm / ovf 領域 | 100.00% |
| `cg_enc` | E2M1 全 8 コード、e_rel の各領域、タイ点命中 | 100.00% |

> **解決済みの差異**: 段階 7 で追加した `tb_bdp_flow` (`make sim-sukima-flow`) は
> 長く sukimasim で結果が一致しなかった。原因は 2 層あり、**2026-08-21 時点で両方とも
> 解決している** (sukimasim 0.9.9.2 / バイナリ 2026-08-20 09:03 ビルド)。
>
> - **層 1 = sukimasim Issue #1204 (修正済み・close)**。`mxfp4_ref_pkg::ref_sop4()` の
>   ローカル `int s` が、`run_scenario()` の `for (int s = 0; ...)` を上書きしていた。
>   ループ変数が sop4 の値に化けて 300 series のシナリオが 1 series しか投入されず、
>   「51〜54 個の結果が出てこない / stall が起きない」という見え方になっていた。
>   真因は綴りの衝突そのものではなく**記憶域の選び方** — 局所宣言が新しい記憶域を作らず、
>   祖先の層にある同じ綴りを更新していた (IEEE 1800-2023 §6.21)。TB 側に入れていた
>   `si` への回避策は撤去済み。最小再現は `repro/func_local_name_clobber_minimal.sv`。
> - **層 2 = sukimasim Issue #1205 (修正済み・close)**。fork 分岐から呼んだ subroutine の
>   値渡し formal が呼び出しごとの記憶域を持たず、呼び出し元の automatic ローカルを
>   隠していた。`push_series` の dynamic array `a` / `b` が
>   `ref_sop4(input logic [135:0] a, input logic [135:0] b)` の formal に隠され、
>   `a.size()` が `x` を返して DUT へ渡すブロックが実質ゼロになる、というのが
>   結果のミスマッチ (`7fc00000` / `00000000`) の正体だった。切り分けの過程で
>   #1218 / #1221 (automatic task の宣言ローカルが呼び出しの寿命を持たない) が分離され、
>   いずれも close。
>
> 現在の実測は Verilator と一致する。既定 N (`n_series=300`) で両者とも
> **1257 checks / 0 errors / results=1250**、`+N_FLOW=3` で両者とも
> **69 checks / 1 error / results=62**。この 1 error は
> `source was never held off; FIFO full path untested` で、`N_FLOW=3` では FIFO 満杯経路に
> 届かないという TB 側の非 vacuous 性チェックが**両シミュレータで同じように**落ちている
> だけであり、シミュレータ差ではない。
>
> 照合するときは **checks と results** を見ること。この 2 つは一致すべき値で、ずれたら
> 本物の差分。**errors の 0/1 は `$urandom` の系列に依存する**ので両者で正当に食い違う
> (末尾 2 つの非 vacuous 性チェックが N と乱数列しだいで成否を変えるため。sukimasim の
> #1205 修正コミット自身が `N_FLOW=20` で sukimasim 137/0 対 Verilator 137/1 と記録している)。
>
> **残る `unique case` の X 警告 192 件は結果に影響しない。** 刺激量 (`N_FLOW` 3 / 300)
> にもリセット長 (4 / 40 サイクル) にも依存せず件数が変わらず、全件が最初のシナリオ行より
> 前に出るので、**t=0 の初期整定に限られる**。件数は e2m1_decode 64 個 x 3 評価の勘定に
> 合う。機構はそこまでで、`mxfp4_fifo` の `rd_valid` が X であることが原因ではない
> (`rd_data` のガードを `(rd_valid === 1'b1)` に変えた双子でも 192 のまま)。
> 4 値シミュレータとして無理のない挙動で、Verilator は `--x-assign 0` のため見えない。

> **Icarus Verilog は使用できない。** 仕様書 5.6 節の LZC は `for` ループ内の `break` を
> 使い、10 章でこれを検証対象言語機能として明記しているが、Icarus Verilog 12.0 は
> `break` 文を未サポート (`sorry: break statements not supported`)。

## 実装状況 (仕様書 11 章 ロードマップ)

| 段階 | 実装物 | 状態 |
|---|---|---|
| 1 | `e2m1_decode` | 完了 (D1) |
| 2 | `elem_mul` + `reduce_tree` | 完了 (D2, R1) |
| 3 | `mxfp4_i2f` + `mxfp4_fp32_add_core` | 完了 (R2a) |
| 3' | `mxfp4_fp32_add_core` 単体 (R2f) | 完了 (加算器の丸め経路を全域検査) |
| 4 | 範囲外規約 + `scale_add` -> `mxfp4_bdp` | 完了 (D3, D4, R2b-R2e, E1, E2, SVA) |
| 5 | `quant_encoder` | 完了 (D5, R3, cg_enc 100%) |
| 6 | `gemm_ctrl_fsm` + PE アレイ -> `mxfp4_gemm_top` | 完了 (E3, cg_bdp 100%) |
| 7 | 発展課題 | 完了 (下表。既定値は Rev.1.3 の規範どおり) |

### 段階 7 (発展課題)

いずれもパラメータで切り替える。**既定値は仕様書 Rev.1.3 の規範どおり**
(FTZ / Algorithm 1 / 統合パス / ready なし) で、既定のままなら回帰結果は
段階 6 までと 1 ビットも変わらない。仕様書 11 章が段階 7 の完了基準としている
「統合パスとのビット一致回帰」は、切替後の版と切替前の版を並走させて掛けている。

| 仕様書 | 切替 | 実装 | 検証 |
|---|---|---|---|
| 3.3 節 ready 拡張と FIFO | `mxfp4_bdp` の `out_ready` / `mxfp4_bdp_fifo` | 下流ストールでパイプ全体を単純ストール。入力 FIFO で上流への組合せパスを遮断 | `tb_bdp_flow` (バックプレッシャ有無で結果一致。SVA `p_hold` / `p_stall_hold` が実効化) |
| 5.7 節 near/far + LZA | `mxfp4_bdp` の `USE_NEARFAR` | near は LZA + 1bit 補正、far は高々 1bit 正規化 | `tb_nearfar` (統合パス版と全出力ビット一致)、`make sim-bdp-nf` |
| 6.3 節 gradual underflow | `mxfp4_bdp` / `mxfp4_fp32_add_core` の `GRADUAL_UF` | 丸めの**前**に指数 1 へ揃えて右シフト。acc の DAZ を外す | `tb_gradual_uf` (FTZ 版と並走。デノーマル出力 14,857 件) |
| 7.7 節 3/4 スケーリング | `quant_encoder` の `UNBIASED_34` | `3m = m + 2m` の 26bit 整数演算で厳密に 3/4 倍 | `tb_quant_q34` (Algorithm 1 版と並走。6.0 超えが 0 件になることを確認) |

本体仕様の発展課題で未実装なのは 5.7 節の **HardFloat 流 recoded 形式** のみ (仕様書も「言及にとどめる」)。

### 3/4 スケーリングの実測 (`make sim-q34 N_Q34=20000`、645,375 要素)

| 指標 | Algorithm 1 | 3/4 スケーリング (4/3 倍で復元) |
|---|---:|---:|
| scaled 値が 6.0 超だった要素 | 20.39 % | 0 % |
| 大きさの偏り Σ(\|dec\| - \|orig\|) / Σ\|orig\| | -0.0453 | -0.0027 |
| 符号付きの偏り Σ(dec - orig) / Σ\|orig\| | -0.0032 | -0.0017 |
| 正規化 RMS 誤差 sqrt(Σerr² / Σorig²) | 0.1450 | 0.1154 |

クランプが構造的に消えることで大きさの偏りが 1/17 に、RMS 誤差が 20 % 縮む。
なお偏りの符号は**負** (量子化値が小さくなる方向) であり、仕様書 7.7 節の
「統計的に正方向へ偏る」とは逆である
([`spec_review_rev1.3.md`](docs/spec_review_rev1.3.md) の D1)。

本実装は`KB_W = (KBLK > 1) ? $clog2(KBLK) : 1`としており、`KBLK = 1`でも動作する。本教材ではこの構成を検査し、8.2節の古い非対応の記述も修正した。

## 仕様書との関係

実装・検証の過程で Rev.1.0 の骨格コードに誤りを 6 点 (B1〜B5 と A1)、Rev.1.1 に 2 点
(B6 / B7) 見つけ、いずれも仕様書側で修正された。**取り込み元の実装は Rev.1.3 に追従している。
以下は Rev.1.2 へ至る修正の履歴であり、本教材の追加修正は教材のREADMEに記録する** (Rev.1.2 の骨格コードを機械抽出して検証した結果は
[`docs/spec_review_rev1.2.md`](docs/spec_review_rev1.2.md) を参照)。

やり取りの記録:

| 文書 | 内容 |
|---|---|
| [`spec_feedback_rev1.0.md`](docs/spec_feedback_rev1.0.md) | Rev.1.0 への指摘 (B1〜B5 / C1〜C5) と A1 の検証 |
| [`spec_review_rev1.1.md`](docs/spec_review_rev1.1.md) | Rev.1.1 レビュー (B6 / B7 / C6〜C8) |
| [`spec_review_rev1.2.md`](docs/spec_review_rev1.2.md) | Rev.1.2 確認 (指摘なし) |
| [`spec_review_rev1.3.md`](docs/spec_review_rev1.3.md) | Rev.1.3 レビュー (段階 7 の実装から。D1 / E1〜E3) |

以下は、実装者が押さえておくと理解が早い要点の要約である
(すべて Rev.1.2 で仕様書側に反映済み)。

### 1. 5.6 節 `mxfp4_fp32_add_core` の丸めビット位置がオフバイワン

骨格コードは有効仮数を `norm[27:4]`、guard を `norm[3]` としているが、同じコードが
`ext_s = {1'b0, sig_s, 3'b000}` (= carry 1 + 仮数 24 + GRS 3) で 28bit を構成している。
この構成では

```
bit27      = carry
bit[26:3]  = 24bit 有効仮数
bit2/1/0   = G / R / S
```

が正しい。1bit ずれると丸め判定が常に 1 桁下を見ることになり、RNE が壊れる。
`rtl/mxfp4_fp32_add_core.sv` は後者で実装した。

### 2. 5.5 節の EX1/EX2 段割りがアキュムレータの RAW ハザードを生む

5.5 節は EX1 で「アンパック + 指数比較 + アライン」まで行うとしているが、その構成では
EX1 (投入 +3 サイクル) で `acc` を読み、EX2 (投入 +4) で `acc` を書くことになる。
8.4 節が規定する 1 サイクル 1 ブロックの連続投入では、直前ブロックの累積結果が
3 サイクル分間に合わない。

本実装は 5.6 節の骨格コード (加算器全体が 1 つの組合せモジュール) に従い、`acc` の
読み書きを EX2 の 1 サイクルに閉じ込めた。LAT = 6 と 1 ブロック/サイクルのスループットは
そのまま維持される。`tb_top` の Driver は内積列を隙間なく連続投入するので、この
ハザードがあれば即座に破れる。

### 3. 7.3 節 `e2m1_quantize` の丸め結果の割り当てが 7.2 節の確定表と矛盾

骨格コードは各 binade で `up ? x.5 : x.0` と 2 択にしているが、E2M1 の仮数は 1bit なので
正しくは

```
up    = g & (s | m1)   // m1 を仮数 LSB とみなした RNE の増分
rm1   = m1 ^ up        // 丸め後の仮数ビット
carry = m1 & up        // 次の binade への繰り上がり
```

である。骨格コードでは例えば v = 1.5 (m1=1, g=0) が 1.0 に、v = 1.75 (タイ) が 1.5 になり、
7.2 節の区間表 `[1.75, 2.5] -> 2.0` を満たさない。

さらに `e_rel = -1` (v ∈ [0.5, 1)) だけは扱いが異なる。この区間の E2M1 代表点は 0.5 のみで
0.75 は表現できないため、丸め先は 0.5 か 1.0、中点 0.75 のタイは偶数仮数側 (1.0, M=0) へ入る。
判定は `m1` 単独になる。

### 4. 7.3 節の `unique case` で `is_zero` と `e_rel` 条件が同時成立する

`is_zero` かつ `X_biased > 2` のとき `e_rel <= -3` も成立し、`unique case` の重複違反となる。
`is_zero` を `case` の外へ出した。

### 5. 7.4 節 X_biased の上限クランプが 8bit 演算で桁溢れする

`clamp(amax_exp - 2, 0, 254)` を素直に書くと `amax_exp >= 254 + 2` が 8bit 幅で
`amax_exp >= 0` に潰れ、常に真になる (Verilator の `UNSIGNED` 警告で検出)。
`amax_exp` は 8bit なので `amax_exp - 2` の最大は 253 であり、上限クランプは構造的に
発火しない (`amax_exp = 255` は NaN/Inf として bypass される)。下限クランプのみ実装した。

### 補足: 仕様書の記述から導かれる帰結

- **6.5 節のリファレンスは二重丸めの懸念がある。** double で累積してから FP32 へ丸めると、
  指数差が大きいケースで double 側の丸めが先に効き FP32 の GRS 判定と食い違い得る。
  `tb/mxfp4_ref_pkg.sv` は acc と項を共通指数の広幅整数 (128bit) へ展開して厳密に加算し、
  1 回だけ RNE で FP32 へ丸める。RTL の 28bit GRS パス (アライン量 26 で飽和) とは
  独立な実装なので、飽和シフトの正しさ自体も検証対象になる。

- **9.4 節 `cg_bdp` のサンプルタイミングは 1 つの covergroup では正しく取れない。**
  `cp_sop_*` は S3、`cp_exp_region` は S5 の信号なのに、9.4 節は `cp_a_scale` や
  `cross first, last` と同じ `@(posedge clk iff in_valid)` でサンプルしている。投入時刻に
  サンプルすると 3〜4 サイクル前のデータを拾い、cross や相関が崩れる。`tb_top` は
  covergroup を入力段 / SoP4 段 / 指数段の 3 つに分割し、それぞれ正しい段の valid で
  サンプルする。

- **9.4 節 `cg_enc` の `bins hi = {[3:10]}` は到達不能。** `e_rel = exp_field(Vi) - X_biased`、
  `X_biased = max(0, amax_exp - 2)`、`exp_field(Vi) <= amax_exp` より `quant_encoder` の中では
  `e_rel <= 2` が常に成り立つ。`ignore_bins` として明記した (9.4 節「除外 bin 明記」に該当)。
  `e2m1_quantize` 単体では `e_rel` を直接与えられるので `default` 分岐も検査できる
  (`tb_quant_encoder` の D5 が e_rel x 代表 frac で全数照合している)。
  なお `bins low = {[-10:-3]}` も実際の値域 (-254..2) を覆えないため下限を拡張した。

- **`c_o` は `done` の次サイクルから有効。** 8.4 節は done を cycle `1 + KBLK + LAT` に立てると
  規定し、8.6 節は結果を出力レジスタへラッチすると規定している。両立させると c_o のラッチは
  done アサートのサイクル末になる。結果は次の `start` まで保持されるので、ホストは done 検出後の
  任意のサイクルで読み出してよい。

## 検証環境の注意

- **`PROCASSINIT` 警告を抑制しないこと。** Verilator では宣言時初期値を持つ変数
  (`logic [135:0] a_block = '0;`) をプロセスから駆動しても駆動が反映されず、DUT に 0 が
  入り続ける。この警告を握り潰すと「RTL が常に +0 を返す」ように見える偽の不具合を追うことになる。
  TB の駆動信号に初期値は付けず、リセットシーケンスで初期化する。

- **`$past` の第 1 引数には式ではなく中間信号を渡す。** `$past(in_valid && last, LAT)` の
  ように式を直接渡すと sukimasim 0.9.9.2 は 1 tick 余分に遅れた値を返す
  (IEEE 1800-2023 §16.9.3 に反する。Verilator は規定どおり)。`assign` で単一信号にしてから
  渡せば両シミュレータとも正しく動く。最小再現は
  [`repro/past_expr_minimal.sv`](repro/past_expr_minimal.sv)。
  なお `number_of_ticks` の数え方そのものは両者とも LRM 準拠で、履歴が存在しない区間で
  `x` を返す点はむしろ sukimasim の方が規定に忠実 (Verilator は 2-state のため `0`)。
  2026-08-10 の修正で procedural context の `$past` は直ったが、**concurrent assertion 内は
  未修正**なので中間信号を経由する運用は継続する。

- **日本語コメント中の "Verilator" は行頭に置かない。** `// Verilator ...` は
  `BADVLTPRAGMA` (未知の verilator pragma) として構文エラーになる。

## 参照

仕様書 13 章の参考文献を参照。特に:

- OCP Microscaling Formats (MX) Specification v1.0
- Rouhani et al., "Microscaling Data Formats for Deep Learning" (arXiv:2310.10537)
- IEEE Std 754-2019 / IEEE Std 1800-2023
