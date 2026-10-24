# ツール

ここにあるのは、ケーススタディ（[kirimasim-tests](https://github.com/kurochan001/kirimasim-tests)）で使ったツールの写しです。
どれもkirimasim-testsのディレクトリ構成（`coverage/`の台帳、`tests/`のテスト、`tools/suite_results.py`）を前提にしています。
このリポジトリ単独では動きません。動かすときは、kirimasim-testsの同じ場所に置いて使います。
汎用化（台帳の形式とテストの構成からの切り離し）は、[今後の計画](../README.md#今後の計画)の項目です。

| ディレクトリ | kirimasim-testsでの場所 | 内容 |
| --- | --- | --- |
| `matching_kit/` | `tools/matching_kit/`（テストは`tools/test_matching_kit.py`） | 担当範囲の作成、照合案の受付と即時検査、検証者の判定、統合、2つのシミュレータでの実行、Claude CodeのWorkflowスクリプト（[README](matching_kit/README.md)） |
| `generators/` | `generators/` | 生成テストの枠組み（`common.py`、`generate.py`）と、表形式の要求の例（`keywords.py`：予約語ごとの違法系テスト） |
| `reference/` | `tools/` | 要求台帳の検査・計測・基準値・履歴（`behavior_coverage.py`）、出典監査（`requirement_audit.py`）、仕様の段落の読み出し（`requirement_source.py`）、照合台帳（`requirement_matching.py`）、テストのメタデータと入力ハッシュ（`suite_results.py`） |

一般化したときに、それぞれのツールがどの役割に当たるかは、[一般化した手順書の付録B](../docs/method/spec-to-verification-method.md#付録b元の手順で使った道具との対応)にあります。
