# USBフルスピードのNRZI・スタッフ・誤り判定を検証する

送信器が組み立てたトークンまたはデータパケットを、USBの論理線路を通して受信器へ渡します。Pythonが計算したJ/K/SE0列を送信器の出力と比較し、受信器のPID・ペイロード・誤りフラグも照合します。1クロックがフルスピードの1ビット時間に対応します。[送信RTL](rtl/usb_linecode.sv) ／ [受信RTL](rtl/usb_linecode_rx.sv) ／ [テストベンチ](tb/usb_tb.sv)

## 2種類のパケット

`tok` はPID、11ビットのトークンフィールド、CRC5を送ります。通常のトークンなら下位7ビットがアドレス、上位4ビットがエンドポイントです。SOFでは同じ11ビットをフレーム番号として扱えます。受信側の長さ出力は11ビットの格納幅をバイトに切り上げた2です。`dat` はPID、0～8バイトのペイロード、CRC16を送ります。各バイトはLSBから送り、受信器はEOPの位置から長さを復元します。9～15バイトの開始要求はアイドルのままです。

送信器はSYNC最後の1を含む連続した六つの1の直後に0を挿入し、NRZIで0を遷移、1を同じ線路状態として表します。EOPはSE0を2ビットとJを1ビットです。Jは `01`、Kは `10`、SE0は `00` で表します。受信器はPIDの上下ニブルの反転関係、スタッフ位置、CRCの剰余、EOPの順序と長さを検査します。適用範囲は同期済みの論理ビット列で、PHYのクロック回復、トランザクション応答、ホストのスケジューリングは対象外です。[USB 2.0仕様の7章・8章](https://usb.org/document-library/usb-20-specification)

## 期待値と誤りの注入

Pythonはペイロードの二進多項式を割ってCRC列を生成します。RTL送信器はシフトレジスタでCRCを更新し、受信器は受信CRCまで通した後の剰余をCRC5なら `0x06`、CRC16なら `0xb001` と照合します。単体テストにはUSB-IF公開のCRC5計算例3件、CRC16の既知値、EOP直前のスタッフを含めました。[期待値モデル](run.py) ／ [USB-IFのCRC計算例](https://www.usb.org/sites/default/files/crcdes.pdf)

テストベンチは正しい送信列を検査し、その直後のチャネルでPID反転ニブル、CRC、スタッフの各ビット、またはSE0の長さを個別に変えます。受信完了が1回だけ発生し、該当する誤りフラグだけが立つことを確認します。[要求カタログ](requirements.json)には通常受信、ゼロと非ゼロ、スタッフ挿入、4種類の誤り、送信中のリセットからの復帰の計9目標があります。

| 変異 | 最初の検出 |
| --- | --- |
| 7個目の1までスタッフ挿入を遅らせる | USB_STUFF |
| 送信CRCレジスタを0で初期化する | USB_CRC |
| 受信側のPID反転検査の判定を反転する | USB_PID |
| NRZIで遷移するビットを1に入れ替える | USB_LINE |

## 実行と確認結果

```sh
python3 examples/local-usb-linecode/run.py --out artifacts/usb-linecode-smoke
python3 examples/local-usb-linecode/run.py --profile nightly --out artifacts/usb-linecode-nightly
python3 -m unittest discover -s examples/local-usb-linecode/tests -v
```

2026-11-23に両構成でsmoke計12実行、nightly計16実行が合格しました。各構成のカバレッジは9/9、変異は両構成で計8/8を検出。単体テストは7件合格。smokeは8個のランダムパケット、nightlyは30個ずつ3 seedを固定ケースに追加します。
