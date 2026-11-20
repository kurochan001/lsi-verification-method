# PWMをRCに通してADCの取り込み時刻を比較する

同じPWMをRC回路に入力しても、コンデンサーの電圧は周期内で変わります。この例では、取り込み時刻を充電中から放電中へ移し、ADCのコードがどう変わるかを確認します。[中央揃えPWMからのADC起動](../local-pwm-adc/README.md)と[ADCの変換制御](../local-adc-conversion/README.md)のRTLをそのまま使います。

## 信号の流れと時刻

1. IcarusでPWMの実出力を全クロック観測し、独立に計算したPWMと起動イベントに一致することを確認します。クロックは10µs周期で、PWMの1周期は16クロック（160µs）です。
2. 観測したPWMを0V／2.4Vの区分線形電圧源へ変換します。各エッジを時刻Tとすると、電圧源の変化はTから始まり、2nsのランプで新しい値へ移ります。ngspiceで1kΩと47nF／100nFのRC回路を解きます。
3. ngspiceが各クロック時刻に計算したコンデンサー電圧を、最も近い整数µVへ変換します。同じPWM設定でRTLを再実行し、その時刻の電圧をADCに再生します。ADCは起動から2クロック後に取り込み、さらに4クロック後にコードを出します。1 LSBは12500µVです。

SPICEの時刻0は最初のリセット入力行の立上りです。ADCで扱う時刻は、そこから何クロック経過したかで表します。Tで読み取るのは、その時刻のPWM更新による充放電が始まる直前のコンデンサー電圧です。ngspice側にはクロック時刻をブレークポイントとして与え、指定時刻の解がなければ失敗にします。初期電圧は0Vです。

## 期待値と検出する誤り

- PWMと起動イベントは、周期内の位置から求めた期待値と全クロックで照合します。ADCコードは、実際に取り込むべき時刻の電圧から求め、結果の時刻・件数も照合します。
- コンデンサー電圧の期待値は、PWMの理想値から求めます。2nsのランプ区間では一次RCの線形入力に対する解析解、平坦区間では指数応答を使います。全クロックでngspiceとの差を0.5mV以内とし、充電と放電の両方を観測します。
- 同じPWM波形に対して、上りカウント1／5の起動を比較します。取り込みはそれぞれカウント相当3／7で、時間差は40µsです。両ケースのPWM波形が全周期で一致し、最後の変換コードが3以上離れることを要求します。
- 別の試験では、周期境界でdutyと起動位置を変えます。seedで変化を再現できます。
- 意図的に抵抗を2倍にすると `ANALOG_RC`、ADCへ1クロック前の電圧を再生すると `ADC_CODE` で失敗します。このラベルが一致する場合だけ、誤りを検出したと判定します。ツール異常やCSV欠損は回帰エラーです。

標準試験の最後のPWM周期で、時定数47µsの変換コードは早い取り込みで144、遅い取り込みで81でした。時定数100µsでは113と89でした。3.2V相当の8bit変換モデル上の整数コードです。同じdutyでも、取り込み時刻によって結果が変わることを再現できます。

## 実行と出力

Python 3、Icarus Verilog、vvp、[固定版ngspice共有ライブラリー](../../tools/ENVIRONMENT.md#ngspiceとspice協調例)を使います。配布された準備スクリプトで作成した `lsi-ngspice-config` を指定します。

```sh
python3 examples/local-pwm-spice/run.py \
  --ngspice-config artifacts/toolchains/ngspice/install/bin/lsi-ngspice-config \
  --seed 42 --waves --out artifacts/pwm-spice-wave

python3 tools/run_regression.py --example local-pwm-spice --profile nightly \
  --tool-bin artifacts/toolchains/ngspice/install/bin --out artifacts/pwm-spice-nightly
```

2種類の時定数を実行します。smokeはPWM 12周期とduty変更1 seed、nightlyは24周期とduty変更3 seedです。構成ごとの目標・誤り注入・ツールとソースの確認を含め、JUnitはsmoke 15件／nightly 19件です。

- `rc47us/early/comparison.csv` と `rc47us/late/comparison.csv` で、PWM、起動、取り込み時刻、解析解、ngspice電圧、ADCコードを比較できます。たとえば `sample=1` の行で電圧を読み、4行後の `adc_valid=1` の行で結果を確認します。
- `plant.cir` は生成した回路、`ngspice.csv` はクロック時刻ごとの解です。`--waves` を指定すると `pwm/trace.vcd` と `adc/trace.vcd` を保存します。
- [run.py](run.py) が実行計画と判定、[solve.py](solve.py) がngspiceの実行、[model.py](model.py) が期待値、[pwm_spice_tb.sv](tb/pwm_spice_tb.sv) がRTLの入力・観測を担当します。[要求と目標](requirements.json)は3要求・6目標です。

実行範囲は、ADCの結果がPWMへ戻らない一方向の接続です。ADCのサンプルホールド回路・入力負荷・ノイズや、実PWMの電力段の評価には、対応する回路モデルと測定が必要です。実行したツールと結果は[実行記録](../../PROVENANCE.md#pwm-spice)を参照してください。
