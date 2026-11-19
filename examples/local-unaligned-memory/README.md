# 非整列アクセスの分割とエンディアン変換

[RAMポート比較](../local-ram-ports/README.md)では拒否する、ワード境界に揃わないアクセスを扱います。バイトアドレスの要求を32／64bitの同期RAMへの最大2アクセスへ変換し、データ・Byte enable・エンディアン・途中エラー・リセットを検証します。[4教材の入口](../local-memory-common/README.md)にもまとめています。

## アドレスとデータの例

32bit RAMへアドレス`0x03`から4バイトの値`0x11223344`を書きます。little endianなら、Byteアドレス`0x03～0x06`へ順に`44 33 22 11`を書きます。RAMのWord 0のByte enableは`1000`、Word 1は`0111`です。他のバイトを保持します。

big endianなら同じByteアドレスへ`11 22 33 44`を書きます。本例のbig endian設定は要求値と連続バイト列の対応を変えるもので、RAM内部の物理的なレーン番号は変えません。RAMのレーン0は常にワードデータの`[7:0]`です。要求データの下位`8*req_size`bitが値を表し、それより上は使いません。

Pythonの期待値は、アドレスをワードへ切り詰める処理を持たない独立したバイト配列です。書いたサイズでの読戻しに加え、全ワードを読み直します。書込みと読出しの両方で同じレーンを取り違え、単純な自己読戻しだけでは隠れる誤りも検出します。

## 要求・応答・エラーの契約

- `DATA_W`は32／64、既定32、深さは16ワードです。上位のアドレスは16bitのByteアドレス、RAM側はワード番号です。ベースは0です。
- `req_size`は1～ワード内バイト数です。1・2・4・8だけに限定せず、3や7バイトも扱います。0、ワード幅を超えるサイズ、全転送がRAM内へ収まらない要求を、RAMへ出す前にエラーにします。
- `req_valid && req_ready`の立上りで要求を保持します。応答は`rsp_valid && rsp_ready`で受理します。応答停止中はデータとエラーを保持し、次の要求を待たせます。
- RAMは単一ポート・同期読出しです。`ISSUE`で1ワード分のアクセスを発行し、`WAIT_DATA`で読出し値を集め、必要なら次のワードを処理します。書込みはByte enableで非選択バイトを保持します。
- `fault_second`は検証専用フックで、受理時に保持します。有効なら境界をまたぐ要求の2ワード目をRAMへ出さず、エラーにします。1ワードで完了する要求には影響しません。
- 2ワードの書き込みは**原子的ではありません**。後半が失敗しても前半の成功分は残り、ロールバックしません。読出しエラーは応答データ全体を0にします。
- 同期・アクティブLowリセットは保留処理と応答を破棄します。RAMは保持します。1ワード目の書込み後にリセットすると、その分だけが残ります。リセット中はネイティブRAMアクセスを発行しません。

これは教材独自のByteアクセスインターフェースです。AXIやAHBの非整列アクセス全体への適合性を主張する例ではありません。分割転送とエラーの契約を独立して学べる構成です。

## 検証項目

全開始オフセット×全有効サイズ、境界に収まる／またぐ転送、両エンディアン、32／64bit、下限・上限・範囲外・不正サイズ、後半エラー、前半完了後のリセット、応答停止、ランダムアクセスを実行します。上位の要求を受理した後は入力値を変え、保持した値を使うことも確認します。

データだけでなく、実際のネイティブRAMアクセス数も照合します。不正要求は0回、通常の分割は2回、後半をエラーにした要求は1回です。意図した後半エラーは`EXPECTED_LIMITATION`として表示し、その後にRAM全体を読み直して残存範囲を判定します。

4種類の誤実装は、バイトオフセットの無視、big endianの無視、Byte enableの無視、後半アクセスの欠落です。[要求と目標](requirements.json)の通常到達と、変異の検出は別に数えます。

```sh
python3 examples/local-unaligned-memory/run.py --out artifacts/unaligned-smoke
python3 examples/local-unaligned-memory/run.py --profile nightly --seed 42 --out artifacts/unaligned-nightly
python3 examples/local-unaligned-memory/run.py --waves --out artifacts/unaligned-wave
python3 -m unittest discover -s examples/local-unaligned-memory/tests -v
```

smokeは4構成×1 seed、nightlyは4構成×3 seedです。固定試験に加えるランダム操作は各seed 24／96組で、各書き込み後に対象と全ワードを照合します。JUnitは14／22件、セルフテストは4件です。波形は`w32-little/seed17/trace.vcd`などで、`base`、`progressed`、`native_address`、`native_strb`、応答を追います。

## ファイルと確認範囲

[unaligned_memory.sv](rtl/unaligned_memory.sv)が分割器、[byte_word_ram.sv](rtl/byte_word_ram.sv)がByte enable付き同期RAM、[model.py](model.py)が独立した参照モデル、[unaligned_memory_tb.sv](tb/unaligned_memory_tb.sv)が自己判定TB、[run.py](run.py)が回帰です。

2026-11-20にIcarus Verilog 14.0開発版でsmoke／nightlyを実行しています。正確な版・証跡は[実行記録](../../PROVENANCE.md#memory-integration-four)を参照してください。特定RAMマクロ、AXIバースト、キャッシュ整合性、複数未完了要求、分割書込みの原子性は対象外です。他シミュレータでの実行や実装後タイミングは未確認です。
