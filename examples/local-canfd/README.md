# CAN FDの送信ビット列を検証する

11ビット識別子のデータフレームを1台の送信器で組み立て、送信ピンの各ビットと保持クロック数をPythonの期待列と照合します。対象はClassical CANとISO CAN FDです。フレーム形式、長さ、CRC、スタッフ、速度切替を個別に観察できます。[RTL](rtl/canfd_tx.sv) ／ [期待値モデル](run.py) ／ [テストベンチ](tb/canfd_tb.sv)

## 入力と時間

アイドル中の `start` で `identifier`、`fd`、`brs`、4ビットの `dlc`、512ビットの `payload` を取り込みます。最初のバイトは `payload[511:504]` です。FDのDLCが0～8なら同じバイト数、9～15なら順に12、16、20、24、32、48、64バイトを送ります。Classical CANではDLCが8を超えてもデータ長は8バイトです。

`bit_valid` は各ビットの開始を表し、`stuffed` は挿入ビットを示します。通常速度は `x3` で3クロック、`x5` で5クロック、データ速度はどちらも1クロックです。BRS付きではBRSビットの次からCRC列の末尾までを高速とし、CRCデリミタから通常速度に戻します。BRSビット・CRCデリミタ内のサンプル点での切替を整数クロックの境界で近似しています。ACKスロットの送信ピンはリセッシブです。仲裁・ACK観測・再送・物理層の遅延は扱う範囲の外です。[BoschのCAN FD解説](https://www.bosch-semiconductors.com/products/ip-modules/can-protocols/can-fd/)

## 期待値と検出条件

Pythonは論理フィールドを送信順に並べ、二進多項式の割り算でCRCを求めます。RTLは順次回路でビットを生成し、1ビットずつCRCレジスタを更新します。Classical CANのCRC15にはスタッフを含めず、SOFからCRC列末まで動的スタッフィングを適用します。FDのCRC17は16バイトまで、CRC21は20～64バイトで使います。FDではデータ部までの動的スタッフと、3ビットのGray符号によるスタッフ数および偶数パリティをCRCに含めます。CRCフィールドの先頭と論理4ビットごとに直前の反転ビットを挿入します。[BoschのCAN FD誤り検出に関する論文](https://www.bosch-semiconductors.com/media/ip_modules/pdf_2/papers/icc_2015_mutter_1.pdf) ／ [CiAによるCRCの解説](https://www.can-cia.org/can-knowledge/cyclic-redundancy-check-crc-in-can-frames)

固定ケースには空フレーム、16／20バイトのCRC境界、64バイト、BRSの両値、送信中のリセットと復帰を含めました。テストベンチは低速ビットの保持中も `tx` と `bit_valid` を監視します。検査を通ったフレーム末尾で[10個の目標](requirements.json)の該当項目を記録します。単体テストでは全16通りのFD DLC、固定スタッフ数の6／7ビット、CRC15の既知値、期待列に誤りを入れたときの不合格も確認します。

| 変異 | 最初の検出 |
| --- | --- |
| 動的スタッフを6連続まで遅らせる | CANFD_STUFF |
| 20バイト以上でもCRC17を選ぶ | CANFD_CRC |
| BRSでデータ速度へ切り替えない | CANFD_STREAM |
| FDのFDFをドミナントで送る | CANFD_STREAM |

## 実行と確認結果

```sh
python3 examples/local-canfd/run.py --out artifacts/canfd-smoke
python3 examples/local-canfd/run.py --profile nightly --out artifacts/canfd-nightly
python3 -m unittest discover -s examples/local-canfd/tests -v
```

2026-11-23に両構成でsmoke計12実行、nightly計16実行が合格しました。各構成のカバレッジは10/10、変異は両構成で計8/8を検出。単体テストは6件合格。smokeは固定列に4個のランダムフレームを加え、nightlyは12フレームずつ3 seedで確認します。
