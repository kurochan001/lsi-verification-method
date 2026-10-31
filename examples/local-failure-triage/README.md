# 失敗解析から修正後の回帰試験まで

イベント優先の割り込み回路を使い、RTL、期待値、SVA設定、ツール不足、時間切れを切り分けます。意図的な誤りを除いた後、**同じ入力ファイルの内容**で再実行し、正常完了を確かめます。

```sh
python3 examples/local-failure-triage/run.py --out artifacts/failure-triage
python3 examples/local-failure-triage/run.py --profile nightly --out artifacts/failure-triage-nightly
```

Python 3.10以上、POSIX、Verilator 5.052、C++20コンパイラー、makeが必要です。UVMライブラリは使いません。nightlyは追加のランダム入力を32行から256行へ増やします。両プロファイルとも親のJUnitは12判定です。

| 注入する問題 | 実際の証跡と切分け |
| --- | --- |
| RTLをクリア優先にする | 比較器の`TRIAGE_COMPARE`で停止し、独立したPython仕様値とRTLが不一致 |
| 期待値だけクリア優先にする | 同じ比較ラベルで停止するが、RTLは仕様値と一致し、参照モデルが不一致 |
| SVAと比較器を止める | シミュレーションは通るが、ネイティブcoverの必須ヒットがなく、検査設定不良として拒否 |
| 存在しないシミュレーターを指定 | 実際の起動失敗を記録。RTLの合否は未確認 |
| 終了しないシミュレーション | 実際の壁時計時間の上限で停止し、子プロセス群を終了。誤実装の検出には数えない |

ビルド1件、通常実行1件、各問題の切分けと修正後確認10件を判定します。5種類の元の失敗は意図した実習結果ですが、原因が異なる異常終了や波形・観測の欠落は成功と扱いません。

各問題のディレクトリに`issue.md`を生成します。`failure`と`fixed`に入力、コマンド、ログ、波形、仕様値との比較結果を保存し、ルートには入力ハッシュ・全計画・JSON・JUnitを残します。起動不能時に波形がないことは、その状態として明示します。

共有するRTLは[IRQ・CDC例](../local-irq-cdc/README.md)の`irq_pending`です。独立した期待値は、仕様の「イベント集合と保持状態からクリア分を除き、リセットを適用する」という真理値計算で作ります。この小さな契約に対する分類であり、任意の回路の根本原因を自動で特定するツールではありません。

関連：[失敗解析の手順](../../docs/method/failure-analysis.md)、[不具合票](../../docs/templates/verification-issue.md)、[AI提案のレビュー](../local-ai-review/README.md)。
