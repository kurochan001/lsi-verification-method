# 中央揃えPWMから指定位置でADCを起動する

中央揃えPWMのカウント位置から、ADCの変換開始イベントを作る教材です。[相補PWMとデッドタイムの例](../local-motion-io/README.md)に続いて、PWMによるサンプリング時刻の指定を学べます。ADCは[単体教材](../local-adc-conversion/README.md)のRTLと独立モデルを再利用します。実機でのPWMトリガーの設定例も参照できます。 [TIのePWMによるADC起動](https://software-dl.ti.com/C2000/docs/C2000_driverlib_api_guide/f2838x/build/html/modules/epwm.html)

取り込み時刻によってADCコードがどう変わるかは、[PWMをRCに通すSPICE実習](../local-pwm-spice/README.md)で確認できます。

## 1周期の規則

`HALF_PERIOD=5` なら、カウント値は `0, 1, 2, 3, 4, 5, 4, 3, 2, 1` です。周期は10クロックで、0と5はそれぞれ1回だけ通ります。比較値を2に設定すると、上りの2でだけ `adc_start` が成立します。下りの2では起動しません。ADCが電圧を取り込むのは、その開始イベントを受理してから `ACQUIRE` サイクル後です。

- `cfg_duty` は0〜`HALF_PERIOD` です。0は常にLow、最大値は常にHighです。中間値dはカウント値がd未満のときHighなので、1周期のHighは `2*d-1` クロックです。
- `cfg_sample` は1〜`HALF_PERIOD-1` です。設定はまずshadowに保存し、2値を周期先頭のエッジで一緒に反映します。周期先頭と同じエッジの有効な設定は、その周期から使います。不正値は拒否して `cfg_error` を出します。
- `enable=0` で次のADC起動を抑止し、PWMを次のクロックエッジでLowにします。周期のカウントを初期位置へ戻し、設定は保持します。開始済みのADC変換は継続し、同期リセットで取り消せます。
- ADCが前の変換や結果を処理中でも、PWMの周期は進みます。そのまま到来した次の起動イベントはADC側で拒否し、`overrun` を報告します。0%や100%でも、有効なら設定した位置の起動イベントは出ます。

## 試験

Pythonは経過時間の剰余から周期内の位置と上下方向を求め、各エッジのPWM出力・有効設定・ADC起動・変換結果を予測します。TBはADCが見た起動イベントをエッジ直前に、PWMとADCの登録出力をNBA更新後に比較します。

上り条件、下りの抑止、比較値と同時の無効化、0%／100%、同時・周期途中・不正な設定、ADC結果待ちでのoverrun、変換中の協調リセット、seed付きの設定変更を確認します。変異は、上下の両方で起動、周期途中の設定反映、起動の1カウントずれ、周期境界の新しい設定の取りこぼし、無効化中の起動です。

## 実行と波形

```sh
python3 examples/local-pwm-adc/run.py --out artifacts/pwm-adc-smoke
python3 examples/local-pwm-adc/run.py --profile nightly --seed 42 --out artifacts/pwm-adc-nightly
```

[pwm_adc_trigger.sv](rtl/pwm_adc_trigger.sv)がPWMと起動信号のRTL、[pwm_adc_tb.sv](tb/pwm_adc_tb.sv)がADCとの接続・自己判定、[model.py](model.py)が期待値、[requirements.json](requirements.json)が4要求・12目標です。周期16／10の2構成で実行し、smoke／nightlyのJUnitは16／20件です。`period16-boundaries/wave.vcd` の `level` と `up`、`active_sample`、`adc_start`、`busy`、`result_valid` を並べると、上下のどちらで起動したかと値が出るまでの遅延を追えます。

ランナーとモデルのセルフテストは9件です。起動が搬送波の1周期に1回であること、デューティ0%と100%、不正な設定の拒否、ADC側の列がADCのモデルの再実行と一致すること、計画の名前とラベル、seedの再現、全構成の実行と証跡、`--demo-bug`の終了コード、期待値を書き換えたときにテストベンチが不合格にすることを確かめます。2026-11-21のレビューで、この例にセルフテストがないことが分かり、追加しました。

```sh
python3 -m unittest discover -s examples/local-pwm-adc/tests
```

PWMとADCは同一クロックで接続しています。PWMの電力段、ゲートドライバ、アナログの電流波形、最適なサンプリング位置の評価は別の確認です。使用したシミュレータと検証結果は[実行記録](../../PROVENANCE.md#pll-adc-pwm)を参照してください。
