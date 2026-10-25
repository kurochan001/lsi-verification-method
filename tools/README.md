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

## 動作確認する場所と依存ファイル

元の構成を持つkirimasim-testsのチェックアウトを用意します。このリポジトリの`tools/`全体をそのまま重ねるのではなく、上表の対応先へ復元します。特に、`reference/*.py`は元の`tools/`直下、`test_matching_kit.py`は元の`tools/test_matching_kit.py`、`generators/`は元のリポジトリ直下です。複製元のパスと版は[由来](../PROVENANCE.md)で確認できます。

次の依存ファイルは、このリポジトリには含めていません。

- `coverage/`の要求・節・出典監査・照合・判定の台帳と、証跡。
- `tests/`のテスト、期待値、補助ファイル。
- `tools/run_icarus.py`と`tools/run_verilator.py`など、シミュレータのランナーとその依存モジュール。
- `generators/generate.py`が読み込む、予約語以外の生成器。`generate.py`は元の全生成器を前提にするため、ここにある3ファイルだけでは実行できません。
- 規格のPDFと抽出テキスト。出典を読み出す場合は、リポジトリ外の配置先を`IEEE1800_SOURCE`または`requirement_source.py --source`で指定します。

同期基準の`3faf239`の構成に復元した場合、元のリポジトリのルートで、ツールの単体テストを次のように実行できます。このコマンドはシミュレータによる全スイート実行とは別の確認です。

```sh
python3 -m unittest discover -s tools -p 'test_*.py'
```

台帳の検査・計測を行う場合も、元のリポジトリのルートで行います。ここで実行してパスだけを修正しても、台帳とテストが欠けたままでは検証にはなりません。一般化文書で追加した構成別の判定やサインオフ記録を自動検査する仕組みは、今後の汎用化の対象です。
