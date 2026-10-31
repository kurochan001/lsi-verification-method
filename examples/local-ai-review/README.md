# 保存したAI提案をレビューする演習

要求の抜け、誤った`$past`、空虚な成立、DUTと参照モデルの相関した誤りを、実際に動かして調べます。`proposals.json`は本リポジトリ向けに作成した教材用の提案サンプルで、特定モデルの実際の出力や評価結果ではありません。外部AI APIやAPIキーは不要です。

```sh
python3 examples/local-ai-review/run.py --out artifacts/ai-review
python3 examples/local-ai-review/run.py --profile nightly --out artifacts/ai-review-nightly
```

Python 3.10以上、POSIX、Verilator 5.052、C++20コンパイラー、makeを使います。UVMは不要です。[失敗解析例](../local-failure-triage/README.md)のテストベンチと独立したPython仕様モデル、IRQ例のRTLを再利用します。ビルド1件、悪い提案4件の却下確認、修正版の通常実行1件と変異3件の検出で、JUnitは9判定です。

| 提案 | 実行とレビューで示す問題 |
| --- | --- |
| `missing-condition` | 同時イベント＋クリアを省くと、正常RTLもクリア優先の誤RTLも通る。要求の欠落・collision未達・変異の生存を記録 |
| `wrong-past` | 正常RTLを誤った履歴参照で拒否し、`SVA_PAST`違反を記録 |
| `vacuous-assertion` | 前件が`event && !event`で、比較器を止めた誤RTLが通る。前件cover 0と独立仕様値の不一致を記録 |
| `correlated-model` | DUTと参照モデルを両方クリア優先にしSVAを止めると通る。独立仕様値との双方の不一致を記録 |

修正版では、同時条件・マスク中の保持・pending中のリセットを必須入力に含め、仕様値との比較と正しいSVAを有効にします。正常実行は5つのネイティブcoverがすべて到達し、クリア優先、マスク中のイベント欠落、リセット漏れの3変異は指定比較器で失敗する必要があります。nightlyはランダム入力を32行から256行へ増やします。

`review-decisions.json`へ、提案、検出した問題、期待した問題一覧、採否と根拠の実行を保存します。生ログ・波形・入力・コマンド・ネイティブ`coverage.dat`・ハッシュ・JUnitも残します。悪い提案の終了コード0は、演習で示す見逃しの証跡です。正常RTLの合格証跡や到達率へ混ぜません。

この自動判定は、固定した教材の問題が再現し検出されることを調べるものです。任意の提案に対する汎用AI審査や人の承認ではありません。[AIレビューの手順](../../docs/method/ai-verification-review.md)と[依頼・採否の記録](../../docs/templates/ai-verification-request.md)を使って、実際の対象へ条件を置き換えてください。
