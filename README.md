# LSI検証手法

LSIの仕様書から検証パターンを作り、要求に対する網羅で検証の完了を測る方法を確立するためのリポジトリです。
仕様書を観測可能な最小単位の要求に分けます。そして、要求ごとに、誤実装なら結果が変わる検証を用意します。作った者とは別の者がそれを反証し、版に紐づいた証跡で網羅を計測します。

## 現状

複製資料・ツールの同期基準は、2026-10-25に確認したkirimasim-testsの`main`（[`3faf239`](https://github.com/kurochan001/kirimasim-tests/commit/3faf239af2614fd8d65cf31c54b0f297108704dd)）です。一般化した手順書には、このリポジトリで製品開発向けの追記・改訂をしています。派生元と変更の範囲は[PROVENANCE.md](PROVENANCE.md)に記録しています。

- **手法の一般化文書**：[ロジック半導体の仕様書から検証パターンを作る手順](docs/method/spec-to-verification-method.md)。半導体の仕様書への適用はまだ行っていません。実際の製品開発で機能検証と併せて必要な、クロック・リセット、低電力、タイミング、DFT・量産テスト、物理設計、信頼性、システム統合、ポストシリコンの項目も14節に整理しています。
- **UVMへの適用**：[UVMで要求と検証資産を結び付ける](docs/method/uvm-verification.md)。基本構成、要求IDとの対応、レジスタモデル（RAL）、UARTの例、回帰の合格条件をまとめています。実行可能なUVMテストベンチは今後の適用で用意します。
- **機能間の検証**：[機能間の相互作用とクロス検証](docs/method/feature-interaction-verification.md)。依存関係の洗い出し、同時動作・順序・中断、クロス目標の選定と合格条件をまとめています。イベントとW1Cクリアの競合を、12目標の例として示しています。
- **ランダム検証**：[制約付きランダム検証の計画・実行・完了判定](docs/method/constrained-random-verification.md)。制約、分布、seed、回帰計画、未達への調整、失敗の再現・縮小をまとめています。クロス検証の12目標を探索する、9実行の計画例も示しています。
- **SVAによる検証**：[SVAのアサーションとカバーによる検証](docs/method/sva-verification.md)。assert・assume・cover、サンプリング、空成立、リセット、シミュレーションと形式検証の完了判定をまとめています。イベントとW1Cの競合を使ったchecker例も示しています。
- **covergroupによる機能網羅**：[covergroupで機能を体系的に網羅する](docs/method/functional-coverage.md)。機能一覧からcoverpoint・bin・crossを選ぶ方法、観測と判定、除外とインスタンス別の集計をまとめています。基本動作の16目標を採取するcollector例も示しています。
- **フォーマル検証**：[フォーマル検証の計画・証明・完了判定](docs/method/formal-verification.md)。仮定・初期状態、抽象化・証明の分割、有界検査と非有界の証明、活性、反例・到達性、サインオフをまとめています。小さな割り込みモデルの証明と、誤実装・過剰な仮定の確認例も示しています。
- **実践例（ケーススタディ）**：IEEE 1800-2023（SystemVerilog）の規格を仕様書とみなし、公開のテストスイート[kirimasim-tests](https://github.com/kurochan001/kirimasim-tests)で手法を実践しました。2026-10-24時点の状況は次のとおりです。
  - 全1,740節を確認し、要求12,319行を登録した。
  - 対応済みは7,341要求（暫定設計網羅率59.59%）、合格の証跡があるのは4,135要求（暫定実行確認率33.57%）。本文（1〜40章）だけでは62.57%。
  - 対応するテストのなかった要求に新規テストを書き、2回の独立検証で1,586本のうち1,530本が合格し、1,527本を取り込んだ（56本は欠陥）。
  - 比較用のシミュレータとして Lyra を加え、Icarus Verilog・Verilator・kirimasim と並べて毎晩実行している（nvc も試したが、対応が少ないため外した）。期待値が規格と食い違う疑いのあるテストを、除外の候補として記録している。
  - 解釈保留は46論点のうち27論点を解消した。
  - 上記2回の新規テストと照合案は、作成者とは別の検証者による反証を経て取り込んだ。スイート全体の全テストをレビュー済みという意味ではない。
- **ツール**：ケーススタディで使った照合キット、生成テストの枠組み、台帳と計測の参照実装です。kirimasim-testsのディレクトリ構成を前提にしており、このリポジトリ単独では動きません（[tools/README.md](tools/README.md)）。

## 構成

```text
docs/method/                    一般化した手順書（この手法の本体）
docs/case-study-ieee1800/       もとになった実践の資料（IEEE 1800-2023）
docs/templates/                製品開発で使う記録の雛形
tools/matching_kit/             照合案の受付・検査、検証者の判定、統合、シミュレータ実行、Workflowスクリプト
tools/generators/               表形式の要求から検証パターンを生成する枠組みと、その例
tools/reference/                要求台帳の検査・計測・出典監査・照合台帳の参照実装
PROVENANCE.md                   各ファイルの由来（元のリポジトリのパスとコミット）
```

## 読む順序

1. [一般化した手順書](docs/method/spec-to-verification-method.md)。[機能間のクロス検証](docs/method/feature-interaction-verification.md)、[ランダム検証](docs/method/constrained-random-verification.md)、[SVAによる検証](docs/method/sva-verification.md)、[covergroupによる機能網羅](docs/method/functional-coverage.md)、[フォーマル検証](docs/method/formal-verification.md)、UVMで実装する場合は[UVMへの適用](docs/method/uvm-verification.md)も参照します。
2. [もとになった手順書（IEEE 1800-2023）](docs/case-study-ieee1800/requirements-to-tests-method.md)
3. [要求抽出の結果と台帳見直し](docs/case-study-ieee1800/requirement-extraction.md)と[未解決事項](docs/case-study-ieee1800/requirement-extraction-notes.md)：仕様の曖昧さの扱いの実例
4. [計測規則](docs/case-study-ieee1800/coverage-rules.md)：設計網羅率と実行確認率、証跡の鮮度、AND集合
5. 結果報告の例：
   - [既存テストの照合（20%到達）](docs/case-study-ieee1800/existing-test-matching-20percent-20261023.md)
   - [附属書ヘッダ・VPIテストと照合](docs/case-study-ieee1800/header-vpi-tests-and-matching-20261023.md)
   - [予約語の生成テスト](docs/case-study-ieee1800/keyword-tests-20261024.md)
   - [未対応要求への新規テスト（50%到達）](docs/case-study-ieee1800/gap-tests-20261024.md)
   - [未対応要求への新規テスト、2回目](docs/case-study-ieee1800/gap-tests-2-20261024.md)
6. [検証で見つかった問題の累積](docs/case-study-ieee1800/existing-test-matching-review-20261022.md)と[シミュレータと規格の差異](docs/case-study-ieee1800/simulator-differences.md)：独立検証で何が見つかるかの実例
7. [比較用シミュレータとの不一致の見直し](docs/case-study-ieee1800/lyra-disagreement-review-20261025.md)：oracle に使わない実装を、期待値を見直すきっかけとして使った例
8. [サインオフ記録の雛形](docs/templates/signoff-record.md)：開発段階、構成ごとの判定、証跡、例外承認、変更の影響を記録する

## 今後の計画

1. **手法の改訂**：一般化文書を、ケーススタディで分かったことに合わせて更新し続けます。
2. **ツールの汎用化**：要求台帳の形式を、規格の節構成に依存しない形にします。具体的には、要求ID、出典、種別、観測点、構成、証跡を持つ形式です。照合キットを、kirimasim-testsの構成から切り離します。テストやチェッカー、カバレッジ項目に要求IDを付ける方式に合わせたアダプタを用意します。
3. **パイロット**：小さなIP（レジスタブロックと1つのバスインターフェース）で一周し、次の点を評価します。抽出漏れ、照合の採用率、見つかったバグと仕様の課題、故障注入の検出率、工数。
4. **テンプレート**：サインオフ記録の雛形を起点に、要求台帳、照合案、検証者のチェックリスト、課題票を整備します。手順書の台帳例と記録の雛形は運用案であり、現行の照合キットが対応済みの汎用形式ではありません。

## 注意

- 規格や仕様書の本文は、このリポジトリに入れません。要求は自分の言葉で書き、版と段落を引用します。
- 機密の仕様書を扱う場合は、AIを使える環境と範囲を先に決めます。
- AIによるレビューは、人の承認ではありません。台帳と報告に、担当者と方法を明記します。

## ライセンス

kirimasim-testsから複製した資料とツールは、元と同じApache License 2.0 with LLVM Exceptions（`Apache-2.0 WITH LLVM-exception`）です（[LICENSE](LICENSE)）。
