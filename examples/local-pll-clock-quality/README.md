# PLL出力のパルス幅・周期・ジッターを測る

PLLのクロックが進み、`LOCKED` がHighでも、短いパルスや周期のずれが生じることがあります。この実習では、テストベンチで生成したPLLクロックを既存の[ロック・停止監視回路](../local-pll-recovery/README.md)に接続し、そのクロックのエッジ時刻から別に合否を判定します。

## 測定規則

設定した測定区間の最初の立上りを基準時刻R₀とします。立上りをRᵢ、立下りをFᵢ、公称周期をPとすると、各指標は以下のとおりです。

- High幅はFᵢ − Rᵢ、Low幅はRᵢ₊₁ − Fᵢです。幅を別々に測ることで、周期一定のままHighかLowだけが短くなる場合を検出できます。
- 周期pᵢはRᵢ − Rᵢ₋₁です。公称周期Pからの差が800ps以内であることを確認します。
- TIE（Time Interval Error）はRᵢ − (R₀ + i × P)です。最初のエッジを起点に公称周期で進んだ理想時刻との差が1000ps以内であることを確認します。周波数ずれにより蓄積する誤差もこの判定に入ります。波形への周期の当てはめは行いません。
- 隣接周期の差はpᵢ − pᵢ₋₁です。絶対値が1200ps以内であることを確認します。2つの周期が個別に許容内でも、差が大き過ぎる場合を検出します。

2構成の公称周期は20ns／34ns、High・Lowの最小幅はそれぞれ8ns／13.5nsです。時間精度は1psで、等号を含めて合格とします。これらは教材上の数値です。

## 起動と測定区間

常時動作する10nsクロックでロックと停止を監視します。起動時は `LOCKED=0` とし、短いパルスを与えても下流がリセット中であることを確認します。十分な正常エッジを与えた後に測定区間を開始します。区間内は `LOCKED`、`clock_permit`、`work_reset_n` がHighで、停止通知がLowであることも点検します。

測定器は刺激表のLow・Highの指定値を使わず、シミュレーション上の実際のエッジと `$time` を使います。区間の立上り・立下りと全刺激行数を照合し、途中で測定が途切れた結果を合格にしません。基準を置く最初の立上りより前のLow幅と周期は判定対象から外します。

## 自己判定と異常系

正常の固定試験は、High・Lowの最小幅、周期・TIE・隣接周期の差の上限ちょうどを通過します。seed付き試験では安全な範囲の立上りオフセットとパルス幅を変えます。次の5つは各構成で異なるチェッカーに到達します。

1. High幅だけを最小値より1ps短くします。判定は `PLL_SHORT_HIGH` です。
2. Low幅だけを最小値より1ps短くします。判定は `PLL_SHORT_LOW` です。
3. 公称周期より801ps長い周期を作ります。判定は `PLL_PERIOD` です。
4. 周期を毎回250ps長くして位相をずらします。周期と隣接周期差の条件は通りますが、TIEが1250psで `PLL_TIE` になります。
5. 公称周期+700psの直後に公称周期−700psを与えます。個々の周期は許容内で、隣接周期差1400psが `PLL_CYCLE_STEP` になります。

すべての異常系で、検出時点までロック・動作許可・下流のリセット解除を維持します。予定のラベルによる非ゼロ終了を要求し、ツールエラーや時間切れを検出成功として扱いません。

## 実行と出力

リポジトリのルートから、Python 3・Icarus Verilog・vvpで実行できます。

```sh
python3 examples/local-pll-clock-quality/run.py --out artifacts/pll-quality-smoke
python3 examples/local-pll-clock-quality/run.py --profile nightly --seed 42 --out artifacts/pll-quality-nightly
python3 examples/local-pll-clock-quality/run.py --configuration p20ns --demo-bug 4 --out artifacts/pll-tie-demo
```

最後のコマンドは通常検証の入力にも異常を加えるため、終了コード1が期待結果です。smoke／nightlyのJUnitは16／20件です。各構成で[3要求・7観測目標](requirements.json)を確認します。[run.py](run.py)が回帰、[model.py](model.py)がクロック刺激、[pll_clock_quality_tb.sv](tb/pll_clock_quality_tb.sv)が計測・照合を行います。

ランナーとモデルのセルフテストは8件です。刺激のパルス幅から5つの量を別に計算し直し、正常な刺激がどの上限にもちょうど乗ること、各異常がねらった上限を超えること、測定区間の外の短いパルス、計画の名前とラベル、seedの再現、全構成の実行と証跡、`--demo-bug`の終了コードを確かめます。周期の異常（+801 ps）は次の周期との差も1202 psになり、テストベンチは先に調べる周期の違反として報告します。2026-11-21のレビューで、この例にセルフテストがないことが分かり、追加しました。

```sh
python3 -m unittest discover -s examples/local-pll-clock-quality/tests
```

`p20ns-boundaries/wave.vcd` には `pll_clk`、`measure`、`clock_permit`、`work_reset_n` が含まれます。波形の隣の `wave.vcd.edges.csv` には実測した時刻、High／Low幅、周期、TIE、隣接周期の差をps単位で残します。立上り行の `pulse_ps` は直前のLow幅、立下り行ではHigh幅を表します。測定対象外の周期・TIE・隣接周期差は0です。`p20ns-detect-phase-drift/simulation.log` では、しきい値超過時の値と各状態を確認できます。

クロック外乱はテストベンチで与えます。実PLLの位相ノイズ、RMSジッター、電気的なエッジ、実装後のタイミングや実機の測定は別の確認です。ツールの版と実行結果は[実行記録](../../PROVENANCE.md#pll-clock-quality)を参照してください。
