# 共通DUT lintと警告管理

全例のDUTと共有RTLを[構成台帳](../../tools/lint_targets.json)から読み込み、トップ・パラメーター別にVerilatorでlintします。対象範囲と警告の扱いは[手法書](../../docs/method/lint-and-waivers.md)を参照してください。

```sh
python3 examples/local-lint/run.py --out artifacts/lint-exercise
# DUTの検査だけを実行
python3 tools/run_lint.py --out artifacts/lint-targets
```

Python 3.10以上、POSIX、Verilator 5.052が必要です。構成は固定で、nightlyでも同じ全対象を実行します。統合ランナーでは`--suite all`または`--example local-lint`で選びます。`--suite simulation`や`--suite formal`とは別の静的検査です。

親の12判定は、DUT lintの完了、幅・ラッチ・暗黙ネット・未接続の4負例、警告の追加・解消・ソース変更・未レビュー台帳・診断書式不正の5負例、`run_lint.py`へ不在のVerilatorと応答しないVerilatorを渡した実際のツール不足と時間切れです。後の2件は全対象が指定の理由で失敗することを確認します。意図的な不良RTLは`fixtures`に置き、通常DUTの合格対象や機能カバレッジへ加えません。環境エラーをRTL誤実装の検出成功とは数えません。

`targets`以下に子の全構成のログ・結果・候補台帳・JUnitを保存します。親の12判定と子の構成数は、異なる要求として合算しません。初期台帳には既知指摘が残るため、正常終了でも`diagnostics.json`の`clean`はfalseになり得ます。

ツールの欠落、終了異常、解析できない警告、新規・解消した警告、古いソースや構成、ツール版の差、未完了の対象があれば失敗します。既存台帳を自動更新するオプションはありません。
