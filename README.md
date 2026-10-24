# LSI検証手法

LSIの仕様書から検証パターンを作り、要求に対する網羅で検証の完了を測る方法を確立するためのリポジトリです。
仕様書を観測可能な最小単位の要求に分けます。そして、要求ごとに、誤実装なら結果が変わる検証を用意します。作った者とは別の者がそれを反証し、版に紐づいた証跡で網羅を計測します。

## 現状

- **手法の一般化文書**：[ロジック半導体の仕様書から検証パターンを作る手順](docs/method/spec-to-verification-method.md)。半導体の仕様書への適用はまだ行っていません。
- **実践例（ケーススタディ）**：IEEE 1800-2023（SystemVerilog）の規格を仕様書とみなし、公開のテストスイート[kirimasim-tests](https://github.com/kurochan001/kirimasim-tests)で手法を実践しました。2026-10-24時点の状況は次のとおりです。
  - 全1,740節を確認し、要求12,319行を登録した。
  - 対応済みは7,341要求（暫定設計網羅率59.59%）、合格の証跡があるのは4,135要求（暫定実行確認率33.57%）。本文（1〜40章）だけでは62.57%。
  - 対応するテストのなかった要求に新規テストを書き、2回の独立検証で1,586本のうち1,530本が合格し、1,527本を取り込んだ（56本は欠陥）。
  - 比較用のシミュレータとして nvc と Lyra を加え、Icarus Verilog・Verilator・kirimasim と並べて毎晩実行している。期待値が規格と食い違う疑いのあるテストを、除外の候補として記録している。
  - 解釈保留は46論点のうち27論点を解消した。
  - 作成者とは別の検証者による反証を、全件に適用した。
- **ツール**：ケーススタディで使った照合キット、生成テストの枠組み、台帳と計測の参照実装です。kirimasim-testsのディレクトリ構成を前提にしており、このリポジトリ単独では動きません（[tools/README.md](tools/README.md)）。

## 構成

```text
docs/method/                    一般化した手順書（この手法の本体）
docs/case-study-ieee1800/       もとになった実践の資料（IEEE 1800-2023）
tools/matching_kit/             照合案の受付・検査、検証者の判定、統合、シミュレータ実行、Workflowスクリプト
tools/generators/               表形式の要求から検証パターンを生成する枠組みと、その例
tools/reference/                要求台帳の検査・計測・出典監査・照合台帳の参照実装
PROVENANCE.md                   各ファイルの由来（元のリポジトリのパスとコミット）
```

## 読む順序

1. [一般化した手順書](docs/method/spec-to-verification-method.md)
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

## 今後の計画

1. **手法の改訂**：一般化文書を、ケーススタディで分かったことに合わせて更新し続けます。
2. **ツールの汎用化**：要求台帳の形式を、規格の節構成に依存しない形にします。具体的には、要求ID、出典、種別、観測点、構成、証跡を持つ形式です。照合キットを、kirimasim-testsの構成から切り離します。テストやチェッカー、カバレッジ項目に要求IDを付ける方式に合わせたアダプタを用意します。
3. **パイロット**：小さなIP（レジスタブロックと1つのバスインターフェース）で一周し、次の点を評価します。抽出漏れ、照合の採用率、見つかったバグと仕様の課題、故障注入の検出率、工数。
4. **テンプレート**：要求台帳、照合案、検証者のチェックリスト、課題票の雛形を用意します。

## 注意

- 規格や仕様書の本文は、このリポジトリに入れません。要求は自分の言葉で書き、版と段落を引用します。
- 機密の仕様書を扱う場合は、AIを使える環境と範囲を先に決めます。
- AIによるレビューは、人の承認ではありません。台帳と報告に、担当者と方法を明記します。

## ライセンス

kirimasim-testsから複製した資料とツールは、元と同じApache License 2.0 with LLVM Exceptions（`Apache-2.0 WITH LLVM-exception`）です（[LICENSE](LICENSE)）。
