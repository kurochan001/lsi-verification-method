# 初回の失敗を残して再実行結果を照合する

同期FIFOの深さ1／3／8×幅8／16の6構成を、正式な[統合ランナー](../../tools/REGRESSION.md)から実行します。最初はジョブ全体の上限を極端に短くして実際に時間切れを起こし、次は通常の上限で同じ入力を実行します。[レポートツール](../../tools/REPORTING.md)で履歴と最終結果を照合します。

Python 3.10以上、POSIX、Icarus Verilogを用意します。

```sh
python3 examples/local-regression-report/run.py --out artifacts/report-demo
python3 examples/local-regression-report/run.py --profile nightly --out artifacts/report-nightly
```

smoke・nightlyとも親のJUnitは6判定です。子のFIFOは各プロファイルの全6構成を実行します。親の判定と子の回路試験を重複加算しません。

| 判定 | 期待する結果 |
| --- | --- |
| 初回の実行 | 6ジョブが時間切れになり、全体は終了コード1 |
| 再実行 | 同じ構成・seed・刺激計画で終了コード0 |
| 失敗→成功のレポート | 全履歴を保持し、新しい6結果を採用 |
| 失敗だけを指定 | 採用可能な結果がなく終了コード1 |
| 成功→失敗のレポート | 古い成功へ戻らず終了コード1 |
| 同じ実行の二重指定 | 履歴の重複として終了コード1 |

`report/report.html`をブラウザーで開くと、各ジョブの最初の失敗と新しい成功を読めます。`failed-campaign/`と`repaired-campaign/`には正式な計画・入力・JUnit・元の結果を保存します。意図した失敗を親が検出できたとき、親の診断判定は成功になります。

再実行は上限不足からの回復を示すものです。不安定な試験を自動で成功へ置き換える機能ではありません。レポート自体はジョブを起動せず、人の承認も付けません。
