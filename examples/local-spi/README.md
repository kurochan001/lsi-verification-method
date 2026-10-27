# SPIの4モードをランダムに検証する

8ビット・MSB firstのSPIマスターを、送信／受信データ、転送間隔、busy中の開始要求、転送中リセットを変えて検証します。CPOL／CPHAの4モードと2種類の分周を、ローカルで独立に判定する教材です。

## 1. この回路の仕様

`spi_master`は1つのベースクロック`clk`で動き、`SCLK`、アクティブLowの`CS`、`MOSI`を出力し、`MISO`を入力します。モードと分周はビルド時に固定します。

| モード | CPOL | CPHA | 最初のエッジ（leading） | 次のエッジ（trailing） |
| --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 立上りでサンプル | 立下りで次ビットを出す |
| 1 | 0 | 1 | 立上りでビットを出す | 立下りでサンプル |
| 2 | 1 | 0 | 立下りでサンプル | 立上りで次ビットを出す |
| 3 | 1 | 1 | 立下りでビットを出す | 立上りでサンプル |

この対応は[MicrochipのSPI Transfer Modes](https://onlinedocs.microchip.com/oxy/GUID-A299F4E7-F38C-4DF5-96C0-A87B9F519156-en-US-4/GUID-8A5B8750-B99E-4176-834E-E44E98F4A098.html)を参照しています。以下の開始・完了のタイミングは、この教材独自の仕様です。

- `busy=0`の立上りで1クロックの`start`を受理し、`tx_data`を保持します。同時に`CS=0`、`busy=1`となり、最上位ビットをMOSIへプリロードします。CPHA=1でも早いプリロードを許します。
- `HALF_DIV`はSCLKの半周期をベースクロック数で表し、2または4です。最初のエッジは受理から`HALF_DIV`クロック後で、合計16エッジを出します。
- 最後のエッジからさらに半周期CSを保持し、受理から`17×HALF_DIV`クロック後に`CS=1`、`busy=0`、`done=1`、受信データ確定となります。`done`は1クロック幅です。
- `busy=1`中の`start`は無視し、キューへ残しません。MOSIはアイドル中も最後の値を保持します。SCLKのアイドル値はCPOLです。
- 同期アクティブLowリセットで転送を中断し、CS=1、SCLK=CPOL、MOSI=0、受信データ=0、busy=done=0へ戻ります。中断した転送の完了は通知しません。

## 2. 独立したシリアル刺激と照合

Pythonは送受信バイトと操作列を作ります。テストベンチは、DUTのSCLKを待って動くスレーブではなく、**開始時刻と仕様の分周・位相から計算した予定時刻**でMISOを駆動します。DUTの遅すぎる／早すぎるSCLKに刺激側まで追従することを避け、毎ベースクロック、SCLK・CS・busy・done・MOSIを照合します。送信ビットを予定サンプル時刻で別に収集し、受信データは完了前の保持と完了時の値を確認します。

固定シナリオは7完了転送＋1中断です。0、全1、交互、LSBのみ、MSBのみのデータを双方向で使い、busy中に別データのstartを入れ、中断後の待機と次転送の復帰まで確認します。中断は第5エッジ後の固定位置で行います。追加ランダム操作は、送受信バイト、busy中startの有無、転送間の待ち0〜3を変え、約1/10で転送中リセットを選びます。末尾に正常転送を追加し、中断後の復帰を確認します。

[要求カタログ](requirements.json)は4要求・16目標です。双方向の代表データ10、全二重転送、16エッジ、アイドル、busy中要求の無視、動作中リセット、復帰を各構成で独立に判定します。あるモードの観測で別モードの不足を埋めません。

## 3. 意図的な誤実装の検出

| 番号 | 誤実装 | 期待する検出ラベル |
| --- | --- | --- |
| 1 | 送信データのLSBを反転 | SPI_MOSI |
| 2 | 完了時の受信データのLSBを反転 | SPI_RX |
| 3 | 最初のエッジでCSを解除 | SPI_CS |
| 4 | 半周期を1クロック短縮 | SPI_CLOCK |

変異検出が合格するには、予定のラベルと非ゼロ終了が必要です。通常回路の検証と区別し、変異ケースの観測を通常の16目標には算入しません。

## 4. 実行

[共通の準備・証跡の説明](../local-common/README.md)に従い、リポジトリのルートから実行します。

```sh
python3 examples/local-spi/run.py --out artifacts/spi-smoke
python3 examples/local-spi/run.py --configuration mode3-div4 --seed 42 --iterations 100 --out artifacts/spi-mode3
python3 examples/local-spi/run.py --profile nightly --out artifacts/spi-nightly
python3 -m unittest discover -s examples/local-spi/tests -v
```

構成名は`mode0-div2`から`mode3-div4`までの8構成（mode 0／1／2／3×div 2／4）です。smokeは各構成で32ランダム操作＋末尾の正常転送、nightlyは256操作＋末尾転送を3 seedで実行します。正常時のJUnitは、構成当たりsmoke **7件**、nightly **9件**で、全8構成では**56／72件**です（固定1＋ランダム1／3＋変異4＋ゲート1）。`checks`は操作の検査完了数であり、ベースクロック数ではありません。

```sh
python3 examples/local-spi/run.py --configuration mode0-div2 --demo-bug 4 --out artifacts/spi-intentional-failure
```

このコマンドは通常回路側もクロック周期を誤らせるため、終了コード1と`SPI_CLOCK`による失敗が期待結果です。

## 5. 適用範囲と実行確認

2026-10-27にIcarus Verilog 14.0開発版とPython 3.14.7で全8構成のsmoke／nightly、各16目標、各4変異、確認テスト4件をローカルで確認しました。GitLabへの追加・CI実行は行っていません。

単一スレーブの8ビット転送で、CSを保持した複数バイト、複数スレーブ、LSB first、動作中のモード／分周変更、APB接続は含みません。デジタルの決められたタイミングで比較する教材であり、実デバイスのsetup／hold、配線遅延、ノイズ、周波数限界や規格適合性を保証するものではありません。
