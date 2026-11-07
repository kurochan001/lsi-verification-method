# kirimasimの実行結果

このリポジトリの[Icarus向けの80例・107構成](README.md#smokeを実行した80例)のsmokeを、[kirimasim](https://github.com/kurochan001/kirimasim)で実行した結果です。対象と判定方法、再実行の手順は[事例](README.md)にあります。

## 最新の結果

[![Kirimasim latest](https://github.com/kurochan001/lsi-verification-method/actions/workflows/kirimasim.yml/badge.svg)](https://github.com/kurochan001/lsi-verification-method/actions/workflows/kirimasim.yml)

kirimasimの`main`の最新コミットを、[Kirimasim latest](https://github.com/kurochan001/lsi-verification-method/actions/workflows/kirimasim.yml)で毎日実行しています。[実行の一覧](https://github.com/kurochan001/lsi-verification-method/actions/workflows/kirimasim.yml)から実行を開くと、Summaryに[例ごとの結果](#例ごとの結果)と同じ形式の表が出ます。失敗した構成があれば、その表の前に一覧を出します。Summaryの先頭には、[UVMを処理できるか](README.md#kirimasimがuvmに対応したら)の確認も出ます。

この下の表は、記録した時点の結果です。kirimasimの`main`は1日に何度も進むので、今の状態はバッジと実行の一覧で確認してください。

## 版と環境ごとの結果

新しい順です。どれも80例・107構成のsmoke、seed 17の結果です。

| 日付 | kirimasim | 環境 | 結果 | lowering | シミュレーション | 終了コード0／1 | 異常終了 | 記録 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 2026-11-07 | [`416cca52d085`](https://github.com/kurochan001/kirimasim/commit/416cca52d085665c3fe83d952f61ba66790c03e7) | macOS arm64、AppleClang 21、テストベンチ修正後 | 107／107 PASS | 936 | 2,367 | 1,559／808 | 0 | [由来](../../PROVENANCE.md#testbench-race-fix-20261107) |
| 2026-11-07 | [`b279f56275cd`](https://github.com/kurochan001/kirimasim/commit/b279f56275cd344b4f76cc60bd70eea708341a0c) | GitHub Actions、Ubuntu 24.04、GCC 13.3.0 | 107／107 PASS | 936 | 2,367 | 1,559／808 | 0 | [push](https://github.com/kurochan001/lsi-verification-method/actions/runs/42308647137)、[手動](https://github.com/kurochan001/lsi-verification-method/actions/runs/42312231158)、[JSON](results-20261107.json) |
| 2026-11-07 | [`416cca52d085`](https://github.com/kurochan001/kirimasim/commit/416cca52d085665c3fe83d952f61ba66790c03e7) | macOS arm64、AppleClang 21 | 107／107 PASS | 936 | 2,367 | 1,559／808 | 0 | [由来](../../PROVENANCE.md#kirimasim-latest-ci-20261107) |
| 2026-11-07 | [`d73d8922dfa2`](https://github.com/kurochan001/kirimasim/commit/d73d8922dfa20e19ccb9411adbe42a6d258bb49d) | WSL2、Ubuntu 24.04.1、GCC 13.3.0 | 107／107 PASS | 936 | 2,367 | 1,559／808 | 0 | [由来](../../PROVENANCE.md#wsl-linux-check-20261107) |
| 2026-11-07 | [`d73d8922dfa2`](https://github.com/kurochan001/kirimasim/commit/d73d8922dfa20e19ccb9411adbe42a6d258bb49d) | macOS arm64、AppleClang 21 | 107／107 PASS | 936 | 2,367 | 1,559／808 | 0 | [由来](../../PROVENANCE.md#repository-review-20261107) |
| 2026-11-03 | [`d73d8922dfa2`](https://github.com/kurochan001/kirimasim/commit/d73d8922dfa20e19ccb9411adbe42a6d258bb49d) | macOS arm64、AppleClang 21 | 107／107 PASS | 936 | 2,314 | 1,509／805 | 0 | [JSON](results-20261103.json) |

- **シミュレーションの増加：** 2,314回から2,367回へ増えたのは、kirimasimの違いではありません。[全体レビュー](../../PROVENANCE.md#repository-review-20261107)で、このリポジトリの刺激とテストベンチを増やしたためです。
- **終了コード1：** 意図的な誤実装などを、既存のランナーが予定どおり検出した実行です。未実装、クラッシュ、タイムアウトは異常終了に数え、検出の成功には数えません。
- **WSLと、2026-11-07のmacOSの`d73d8922dfa2`：** 記録に載っているのは全起動の終了コードだけなので、終了コード0の2,495回からlowering 936回を引いた値です。loweringが0以外で終わると異常終了に数えるので、異常終了が0回ならloweringはすべて終了コード0です。
- **テストベンチ修正後：** DMAの2つのテストベンチの競合を直した後の結果です。この表のそれより下の行は、修正の前の結果です。
- **修正前の失敗：** 2026-11-03にテストベンチを直す前の46／107、105／107は、[事例の第2節](README.md#2-実測結果)にあります。

## 記録した最新の実行

`b279f56275cd`を、このリポジトリの`0dd92f8`でGitHub Actionsから実行した結果です。[手動の実行](https://github.com/kurochan001/lsi-verification-method/actions/runs/42312231158)は、キャッシュから戻した同じバイナリーで同じ値でした。Actionsの証跡は14日で消えるので、構成ごとの値を[JSON](results-20261107.json)に残しました。

| 項目 | 値 |
| --- | --- |
| kirimasim | [`b279f56275cd`](https://github.com/kurochan001/kirimasim/commit/b279f56275cd344b4f76cc60bd70eea708341a0c) |
| 計画 | smoke、seed 17、80例・107構成 |
| 結果 | **107／107 PASS** |
| lowering | 936回 |
| シミュレーション | 2,367回（終了コード0が1,559回、1が808回） |
| 異常終了 | 0回 |
| 実行中の入力変更 | なし |

### 例ごとの結果

| 例 | 構成 | 結果 | lowering | シミュレーション | 異常終了 |
| --- | ---: | --- | ---: | ---: | ---: |
| [local-access-control](../../examples/local-access-control/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-activation](../../examples/local-activation/README.md) | 1 | PASS | 10 | 16 | 0 |
| [local-address-map](../../examples/local-address-map/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-ahb](../../examples/local-ahb/README.md) | 1 | PASS | 15 | 18 | 0 |
| [local-apb](../../examples/local-apb/README.md) | 3 | PASS | 12 | 15 | 0 |
| [local-apb-irq](../../examples/local-apb-irq/README.md) | 3 | PASS | 12 | 15 | 0 |
| [local-apb-irq-coverage](../../examples/local-apb-irq-coverage/README.md) | 1 | PASS | 21 | 822 | 0 |
| [local-apb-timer](../../examples/local-apb-timer/README.md) | 1 | PASS | 20 | 24 | 0 |
| [local-apb-uart](../../examples/local-apb-uart/README.md) | 9 | PASS | 54 | 63 | 0 |
| [local-arbiter](../../examples/local-arbiter/README.md) | 3 | PASS | 12 | 18 | 0 |
| [local-async-fifo](../../examples/local-async-fifo/README.md) | 1 | PASS | 20 | 24 | 0 |
| [local-automotive-ecu](../../examples/local-automotive-ecu/README.md) | 1 | PASS | 12 | 26 | 0 |
| [local-axi](../../examples/local-axi/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-axi-reorder](../../examples/local-axi-reorder/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-axi4](../../examples/local-axi4/README.md) | 1 | PASS | 5 | 6 | 0 |
| [local-axis](../../examples/local-axis/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-branch-predictor](../../examples/local-branch-predictor/README.md) | 1 | PASS | 15 | 19 | 0 |
| [local-bus-bridge](../../examples/local-bus-bridge/README.md) | 1 | PASS | 20 | 24 | 0 |
| [local-cache-coherence](../../examples/local-cache-coherence/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-cache-dma](../../examples/local-cache-dma/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-cdc-bridge](../../examples/local-cdc-bridge/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-cdc-handshake](../../examples/local-cdc-handshake/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-clock-reset](../../examples/local-clock-reset/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-conv-window](../../examples/local-conv-window/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-counter-snapshot](../../examples/local-counter-snapshot/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-coverage-feedback](../../examples/local-coverage-feedback/README.md) | 1 | PASS | 5 | 10 | 0 |
| [local-credit-link](../../examples/local-credit-link/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-descriptor-dma](../../examples/local-descriptor-dma/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-divider](../../examples/local-divider/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-dma](../../examples/local-dma/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-dma-ownership](../../examples/local-dma-ownership/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-dram](../../examples/local-dram/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-dsp](../../examples/local-dsp/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-e2e-guard](../../examples/local-e2e-guard/README.md) | 1 | PASS | 12 | 20 | 0 |
| [local-ecc](../../examples/local-ecc/README.md) | 1 | PASS | 5 | 8 | 0 |
| [local-ecc-memory](../../examples/local-ecc-memory/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-failure-reduction](../../examples/local-failure-reduction/README.md) | 1 | PASS | 2 | 9 | 0 |
| [local-fdir](../../examples/local-fdir/README.md) | 1 | PASS | 10 | 52 | 0 |
| [local-fifo](../../examples/local-fifo/README.md) | 6 | PASS | 24 | 30 | 0 |
| [local-i2c](../../examples/local-i2c/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-image-sobel](../../examples/local-image-sobel/README.md) | 1 | PASS | 10 | 14 | 0 |
| [local-image-soc](../../examples/local-image-soc/README.md) | 1 | PASS | 10 | 36 | 0 |
| [local-interconnect](../../examples/local-interconnect/README.md) | 1 | PASS | 5 | 6 | 0 |
| [local-irq-cdc](../../examples/local-irq-cdc/README.md) | 1 | PASS | 5 | 37 | 0 |
| [local-jtag-tap](../../examples/local-jtag-tap/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-load-store](../../examples/local-load-store/README.md) | 1 | PASS | 5 | 6 | 0 |
| [local-lockstep-monitor](../../examples/local-lockstep-monitor/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-mbist](../../examples/local-mbist/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-memory-order](../../examples/local-memory-order/README.md) | 1 | PASS | 5 | 6 | 0 |
| [local-motion-control](../../examples/local-motion-control/README.md) | 1 | PASS | 10 | 44 | 0 |
| [local-motion-io](../../examples/local-motion-io/README.md) | 1 | PASS | 12 | 24 | 0 |
| [local-network-echo](../../examples/local-network-echo/README.md) | 1 | PASS | 10 | 26 | 0 |
| [local-network-soc](../../examples/local-network-soc/README.md) | 1 | PASS | 10 | 44 | 0 |
| [local-packet-crc](../../examples/local-packet-crc/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-packet-switch](../../examples/local-packet-switch/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-performance-monitor](../../examples/local-performance-monitor/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-power](../../examples/local-power/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-priority-irq](../../examples/local-priority-irq/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-recovery](../../examples/local-recovery/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-reduction](../../examples/local-reduction/README.md) | 1 | PASS | 5 | 229 | 0 |
| [local-regression-report](../../examples/local-regression-report/README.md) | 1 | PASS | 24 | 30 | 0 |
| [local-requantize](../../examples/local-requantize/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-retry-link](../../examples/local-retry-link/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-riscv-iss](../../examples/local-riscv-iss/README.md) | 1 | PASS | 5 | 6 | 0 |
| [local-riscv-pmp](../../examples/local-riscv-pmp/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-riscv-traps](../../examples/local-riscv-traps/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-scan-atpg](../../examples/local-scan-atpg/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-secure-lifecycle](../../examples/local-secure-lifecycle/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-sha256](../../examples/local-sha256/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-spi](../../examples/local-spi/README.md) | 1 | PASS | 40 | 48 | 0 |
| [local-store-buffer](../../examples/local-store-buffer/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-stream](../../examples/local-stream/README.md) | 4 | PASS | 16 | 20 | 0 |
| [local-stream-dma](../../examples/local-stream-dma/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-sv32](../../examples/local-sv32/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-systolic-array](../../examples/local-systolic-array/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-timer-watchdog](../../examples/local-timer-watchdog/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-tlb](../../examples/local-tlb/README.md) | 1 | PASS | 10 | 12 | 0 |
| [local-tmr](../../examples/local-tmr/README.md) | 1 | PASS | 10 | 10 | 0 |
| [local-uart](../../examples/local-uart/README.md) | 6 | PASS | 28 | 34 | 0 |
| [local-width-converter](../../examples/local-width-converter/README.md) | 1 | PASS | 10 | 12 | 0 |
| 合計 | 107 | 107／107 | 936 | 2,367 | 0 |

「構成」は統合ランナーが展開するジョブ数です。回数はツールの起動数で、要求数や検証項目数へ合算しません。

## この結果から言えないこと

- 教材側の回路とチェッカーでの互換性の確認で、SystemVerilog全体への適合性の評価ではありません。[確認範囲の外側](README.md#6-確認範囲の外側)にも説明があります。
- Icarusとの出力の照合は、2026-11-03と2026-11-07の2回です。2026-11-07は`416cca52d085`と比べ、生成ファイル4,030個が同一で、ログ2,367個の検査の出力の内容と回数が一致しました。17個は`COVER`の順序だけが違います。出力が一致しても、[実行順の競合](README.md#dmaとディスクリプターdma残っていた同じ競合)がないとは言えません。
- 全80例のnightlyは実行していません。今後の版で同じ結果になることも示しません。
- UVMを使う例は対象外です。kirimasimがUVMに対応したら、[この進め方](README.md#kirimasimがuvmに対応したら)で実行します。
