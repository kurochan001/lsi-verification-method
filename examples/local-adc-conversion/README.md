# ADCの入力取り込み・量子化・変換完了

8bit ADCのデジタル動作モデルを使い、「いつの電圧を、どのコードとして、いつ返すか」を検証します。[SPICE協調例](../local-spice-cosim/README.md)の理想ADCは各制御エッジで電圧をコード化します。この教材では、要求の受理、入力を取り込む時点、変換完了を別のエッジにします。実行にSPICEモデルは不要です。

## 変換の時刻とコード

`start && start_ready` がクロック立上りで成立した時点をTとします。Tから `ACQUIRE` サイクル後の立上りで `vin_uv` を取り込み、さらに `CONVERT` サイクル後に `result_valid` とコードを登録します。標準の `ACQUIRE=2`、`CONVERT=4` なら、T+2で取り込んだ電圧がT+6で結果になります。

`vin_uv` は整数µVで与える符号付き入力です。この例では `floor(vin_uv / LSB_UV)` を0〜255へ飽和させます。`LSB_UV=1000`なら、999µVは0、1000µVは1、254999µVは254、255000µV以上は255です。負電圧は0になります。この丸めと遷移境界は教材の仕様です。

- `busy` は入力取り込み待ちと変換待ちを示します。結果の保持期間は `busy=0` でも、結果バッファが埋まっているため `start_ready=0` になります。
- 未受付の `start` はそのエッジで `overrun` を通知し、進行中のサンプルや保持中の結果を上書きしません。結果の受理と新規開始が重なった場合も、そのエッジの直前に結果が保持中なら新規開始を拒否します。
- `result_valid && result_ready` で結果を受理します。`result_ready=0` の間はコードとvalidを保持します。
- 同期・アクティブLowリセットで進行中の変換と未受理の結果を破棄します。解除後に古い変換完了が出ないことを確認します。

## 試験

Pythonは絶対サイクル番号で取り込みと完了の期限を決め、電圧の遷移境界を二分探索して期待コードを作ります。RTLのタイマーや整数除算を複製しません。TBはエッジ直前の受付とNBA更新後の結果を分けて観測し、X/Zも失敗にします。

全8bitコードの遷移境界について前後1µVを含む電圧を試し、負入力・フルスケール外、上下限の飽和を確認します。要求時・取り込み前後・完了時には異なる電圧を与えます。変換中と結果待ち中の再要求、取り込み待ち・変換中・結果保持中それぞれのリセット、seed付きの連続操作も確認します。

4種類の誤実装は、要求エッジでの早過ぎる取り込み、電圧境界の1µVずれ、受信待ち中の結果消去、動作中の再要求による上書きです。前二者は期待コード、後二者はvalidと変換の進行状況の比較で検出します。

## 実行と波形

```sh
python3 examples/local-adc-conversion/run.py --out artifacts/adc-smoke
python3 examples/local-adc-conversion/run.py --profile nightly --seed 42 --out artifacts/adc-nightly
```

[adc_capture.sv](rtl/adc_capture.sv)が変換モデル、[adc_capture_tb.sv](tb/adc_capture_tb.sv)が自己判定TB、[model.py](model.py)が期待値、[requirements.json](requirements.json)が3要求・8目標です。取り込み／変換を2／4サイクル、1／1サイクルとした2構成で試します。smoke／nightlyのJUnitは14／18件です。`acq2-conv4-boundaries/wave.vcd` では `start`、`vin_uv`、`sampled_code`、`busy`、`result_valid`、`result_ready` を順に確認できます。

このモデルは電圧コードと制御の教材です。サンプルホールド回路の整定、入力負荷、ノイズ、オフセットやゲイン誤差、INL/DNLは、回路モデルや測定結果を使って別途評価します。 [Analog DevicesのADC静特性資料](https://www.analog.com/media/en/training-seminars/tutorials/mt-010.pdf)

使用したシミュレータと検証結果は[実行記録](../../PROVENANCE.md#pll-adc-pwm)を参照してください。
