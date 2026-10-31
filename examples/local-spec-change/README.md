# 同じ入力でAPB＋割り込みの仕様変更を再検証する

[演習用仕様](spec.md)は、W1Cとイベントが同時受理された場合を、r1のセット優先からr2のクリア優先へ変更します。元のリポジトリのRTLは変更せず、保存先へ作ったソースで両版を実行します。[総合演習](../../docs/capstone-apb-irq/README.md)の変更管理を動かす部分です。

## 1. 変更するものと保持するもの

| 対象 | 扱い |
| --- | --- |
| RTL | r2の競合ビットだけクリア優先へ変更する。 |
| 独立した期待値 | ビットごとの更新順序をr2仕様へ変更する。 |
| ネイティブSVA | 別の真理値表でr1／r2の次状態を検査する。 |
| 入力 | 同じwait、seed、境界列・ランダム列を両版へ保存して使う。 |
| 要求・項目・証跡 | 両版を別IDにし、各wait構成で8競合目標を要求する。 |

元のソースが想定した形から変わっていた場合は、文字列の置換を黙って適用せず、アダプタのレビューを要求するエラーで停止します。r2とr1チェッカーを組み合わせた診断は、各waitで`APB_IRQ_PENDING`を検出しなければなりません。

## 2. 実行と計測

POSIX、Python 3.10以上、Icarus Verilog、Verilator 5.052、C++20とmakeを用意します。UVMライブラリは不要です。

```sh
python3 examples/local-spec-change/run.py --out artifacts/spec-change
python3 examples/local-spec-change/run.py --profile nightly --out artifacts/spec-change-nightly
python3 -m unittest discover -s examples/local-spec-change/tests -v
```

smokeは各waitに境界＋1 seed・50ランダム操作、nightlyは境界＋3 seed・各500操作です。wait=0／1／3を両版で実行し、JUnitは34／46件です。全サイクルの応答・状態・IRQ比較、TRACEの観測と確認済み行、VCDを要求します。

Verilatorのネイティブ実行は、各版のwait=1で、同じケース群を連結した入力を使います。4ビットの次状態とIRQのSVA、7つのnative cover、レジスタRTLの行カウンターをDBとactionから検査します。各版は別ビルド・別DBで、率を混ぜません。行カバレッジはレジスタRTLだけが対象で、IRQラッパー全体のコード網羅や全構成の率ではありません。未達の行カウンターも保存します。

既存Icarusテストベンチの`defparam`によるレジスタ変異指定は、ネイティブ正常実行では除きます。明示接続済みの子パラメーターを再指定する形をVerilatorが拒否するためです。正常値0は保持し、検証する回路の動作を変える操作ではありません。

## 3. 古い判定を拒否する

- r2 RTL＋r1の手続き的チェッカー：各waitで予定した不一致を検出する。
- 正しいRTL・参照モデル＋反対の版のSVA：`CAP_PRIORITY`を検出する。
- 正常比較は動かすがSVAを無効化：7 coverが0になり、必須到達を満たさないことを確認する。
- 古い計画ハッシュの証跡：汎用の項目照合が`STALE_PLAN`として拒否する。

診断の失敗・途中の到達を正常な実績へ加えません。[計画JSON](plan.json)の2項目は、変更要求と、4要因×マスク0／1の競合条件を3つのwait構成で確認するものです。元の全要求カタログ・クロスモデルのr2での再承認まで自動化したものではありません。

`evidence.json`と`traceability/`に項目照合、`r1/`・`r2/`にIcarus入力・結果、`native/`に各版のSVA・行カバレッジ・診断、`stale-evidence.json`に拒否理由を保存します。仕様・元のRTL・チェッカー・アダプタの版と、生成したソースや元のログ等のハッシュも保持します。
