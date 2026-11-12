# このリポジトリでの作業の約束

Claude Codeが作業の最初に読むファイルです。背景と確認手順は[引き継ぎ資料](docs/handoff-wsl-linux.md#作業の約束)にあります。

## 報告とpush

- 報告は日本語で行います。
- pushは「コミットしてmainにpush」と言われたときだけ行います。ブランチやpull requestは作らず、mainへ直接pushします。
- 長い作業の途中で、pushせずにローカルでコミットするのは構いません。

## 公開リポジトリとしての注意

- 追跡するファイルに、個人のパス・メールアドレス・マシン名を書きません。
- 商用シミュレータは実行せず、その出力も載せません。規格の本文は写さず、節番号と自分の言葉で書きます。

## kirimasim

- kirimasimのバグと思われるものを見つけたら、確認を待たずに[テンプレート](https://github.com/kurochan001/kirimasim/blob/main/.github/ISSUE_TEMPLATE/bug_report.yml)でBug Issueを発行し、番号を報告します。
- 発行の前に、既存のIssueとの重複、最新の`main`での最小例の再現、テストベンチ側の競合でないことを確かめます。
- kirimasimに関わる作業では、Kirimasim latestのSummaryの先頭でUVMの確認結果を見ます。進んでいたら[UVM例の実行](docs/case-study-kirimasim/README.md#kirimasimがuvmに対応したら)を提案します。

## 変更の前後に実行する確認

```sh
python3 tools/check_docs.py
python3 tools/check_tb_races.py
python3 tools/run_selftests.py --out <新しいディレクトリ>
```

準備の手順と、必要なツールの版は[実行環境](tools/ENVIRONMENT.md)にあります。
