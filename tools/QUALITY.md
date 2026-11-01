# 文書とツールの品質を確認する

READMEから手法書・検証例・用語集・FAQまでを[`check_docs.py`](check_docs.py)で一括確認します。文書の構造と参照の検査であり、説明の技術的な正しさや例の動作は別にレビュー・実行します。

## 文書検査

[文書用環境](ENVIRONMENT.md)を準備してから実行します。

```sh
python3 tools/setup_environment.py --profile docs --out artifacts/toolchains/docs
artifacts/toolchains/docs/python/bin/python tools/check_docs.py --out artifacts/documentation
```

Git管理済みのMarkdownに加え、Gitで無視されていない追加中のMarkdownも対象にします。`artifacts/`や`node_modules/`は対象外です。`--root`で検査するGit作業ツリー、`--node`でNode.js、`--timeout`で図の検査時間の上限を指定できます。出力先は毎回新しくします。

| 検査 | 失敗にするもの |
| --- | --- |
| 内部リンク | 存在しないファイル、対象ファイルを含まないディレクトリ、Gitの対象一覧に含まれない参照先、リポジトリ外への参照 |
| 見出し・アンカー | Markdownへのリンクの移動先が存在しない。日本語、重複見出しの接尾辞、明示したHTMLアンカーも確認 |
| 表・コードフェンス | パイプ形式の表の列数不一致、閉じていないコードフェンス |
| 用語集 | 「用語」を先頭列とする表の空・重複した項目名 |
| FAQ | `Q1.`から始まる質問番号の重複・欠番・順序違い |
| Mermaid | ロックしたMermaidによる構文解析の失敗、実行不能、予定図と結果の不一致 |
| 入力の版 | 実行中の対象文書・リンク先・検査コードの変更、Markdown一覧の変更 |

Mermaidの構文検査はローカルのNode.jsで実行し、外部描画サービスへ文書を送信しません。パース成功だけでは図の読みやすさは分からないため、図を変更したときはGitHubや手元のプレビューで描画・文字の重なりも確認します。外部URLの通信可否、文書内のコード例の実行、GitHub固有の全Markdown拡張はこの検査の範囲外です。

出力の`documentation-check.json`に文書・表・図・用語・質問の件数と文書の問題、`mermaid.json`に図ごとの結果、`mermaid.log`に生ログを保存します。共通の`manifest.json`・`summary.json`・`junit.xml`で予定一覧・入力SHA-256・完了と合否を照合できます。必要なパーサーがない場合や結果が欠けた場合は非0終了し、「図0件の成功」へ置き換えません。

`documentation-check.json`の`document_read_sha256`には、実際に解析した文書のバイト列のハッシュも記録します。マニフェストを作る前に文書が保存し直された場合も、読取り時と記録時のハッシュが異なれば不合格にします。CRLFなどの改行を含めて元のバイト列で照合し、古い内容の検査結果と新しい内容のハッシュを組み合わせて採用しません。

## セルフテスト

```sh
# ツールのみ。文書用のPython・Node依存も必要
artifacts/toolchains/docs/python/bin/python tools/run_selftests.py \
  --scope tools --out artifacts/tool-selftests

# 全例のtestsとtools/tests。full環境とネイティブツールが必要
export PATH="$PWD/artifacts/toolchains/native/install/bin:$PWD/artifacts/toolchains/full/formal/bin:$PATH"
export COCOTB_PYTHON="$PWD/artifacts/toolchains/full/python/bin/python"
artifacts/toolchains/full/python/bin/python tools/run_selftests.py \
  --jobs 2 --timeout 600 --out artifacts/all-selftests
```

[`run_selftests.py`](run_selftests.py)は`examples/*/tests`と`tools/tests`を明示的に列挙し、各グループでunittestを起動します。`--scope tools`なら後者だけです。空のテスト、skip、失敗、時間切れ、結果の欠落を拒否します。全体の`tests.json`にグループとテスト件数、グループ別ログに実際の名前と結果を残します。シミュレータによる全例の動作確認とは別の検査です。

テストコードに加え、Git管理済み・追加中で無視されていないリポジトリ入力全体のハッシュと一覧を固定します。参照モデル・RTL・要求・設定・文書などが実行中に変更・追加・削除された場合は、テストがすべて成功していても結果を採用しません。`--scope tools`でも、テストが例の実装や文書を参照するため、この入力範囲を維持します。指定した出力先と、Gitで無視した`artifacts/`・キャッシュ等の生成物は一覧へ含めません。

ツールのテストには、切れたリンク、不正な図、偽の空のパース結果、誤ったツール版、準備の失敗、異なるコミットのチェックアウト、予定やJUnitの欠落・構造不正、親の外や親自身を参照する子証跡、古いソース、中断時の子プロセス停止などの負例があります。ケーススタディ由来の[参照ツール](README.md#case-study-reference-tools)は元の構成が必要なため、この一覧には含めません。

変更時の[Quality CI](CI.md)は文書・ツール・代表RTLを、毎晩のCIは全セルフテストと[全例のnightly](REGRESSION.md)を実行します。
