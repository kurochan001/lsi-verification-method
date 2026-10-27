# フォーマル反例を入力だけでシミュレーションへ再現する

[既存のFIFO等価性例](../local-equivalence/README.md)の2構成・4変異について、新しくBMCを実行して得たYosys Witnessを変換します。シミュレーションではトップのreset・valid・ready・dataだけを駆動し、内部メモリやポインターをforceしません。

## 再現の条件

1. 各BMCが予定した`ap_control`／`ap_data`違反と反例を持つことを既存の厳密なランナーで確認します。
2. `.yw`の単一posedgeクロック、各ステップのビット配置、入力の幅・既知値、初回リセットを検査します。`init_only`の内部状態を次ステップの入力と取り違えません。
3. 深さ2／4・幅4の同じFIFO RTLへ入力を与え、同じ名前の比較で失敗することを要求します。
4. 同じ入力を正常RTLへ再実行し、独立したPythonキューの期待値とも比較して合格を要求します。

最初のリセット前の未初期化状態は比較せず、その後はリセットエッジの更新前の値も含め、元の同期式miterと同じ観測時点で比較します。任意の初期状態へ依存する反例や、抽象化したデータに依存する反例を自動再現できる汎用変換ではありません。

## 実行

[固定版のフォーマル環境](../local-formal-common/README.md)とIcarusを使います。activateせず、専用Pythonを明示して実行できます。

```sh
python3 examples/local-formal-replay/run.py \
  --formal-python /tmp/lsi-bus-formal-venv/bin/python --out artifacts/formal-replay
python3 -m unittest discover -s examples/local-formal-replay/tests -v
```

各子BMCの上限は`--formal-timeout`、変換後のビルド・実行は`--timeout`です。`--profile nightly`でもフォーマルの固定計画は同じです。8個の新しいBMC、8個の変異再現、8個の正常RTL確認でJUnit 24件です。これは新しい証明8件という意味ではありません。

子のマニフェスト・モデルのプロパティ一覧・反例、`reproducer.json`、`vectors.txt`、ビルド・シミュレーションログ・VCDを保存します。`reproducer.json`には内部状態を含めず、版と構成に対応する固定回帰用入力を残します。タイムアウトや異なるチェッカーの失敗は再現成功にしません。

[SBYの反例](https://yosyshq.readthedocs.io/projects/sby/en/stable/quickstart.html)、[YosysHQのトレース再生](https://yosyshq.readthedocs.io/projects/ap130/en/latest/)を参照した独自の限定変換です。Yosys生成のテストベンチをそのまま実行する例とは区別します。
