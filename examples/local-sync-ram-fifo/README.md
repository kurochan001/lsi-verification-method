# 同期読み出しRAMを使う非同期FIFO

[非同期画像パイプライン](../local-video-async/README.md)のFIFOは、先頭データを組み合わせ出力します。この教材は、読み出しに1／2サイクルかかるRAMを使い、先読み中のデータと出力待ちのデータを管理します。[既存の非同期FIFO](../local-async-fifo/README.md)のGrayポインター同期に、valid/readyの出力保持を加える発展例です。[4教材の入口](../local-memory-common/README.md)にもまとめています。

## 読出し要求と外部への転送を分けます

RAMの読出しを要求しても、データはすぐには返りません。また、返ったデータを受信側がすぐに受理するとも限りません。本例では次の3つを分けて持ちます。

- `fetch_bin`：RAMへ次に読出し要求する位置です。
- `reserved`：RAMへ要求済みで、まだ外部へ渡していない総数です。RAMの読出し待ちと出力キュー内の両方を含みます。
- `rbin/rgray`：**外部で受理済みの位置**です。書込み側へ同期するのはこちらです。

先読みだけで読出しポインターを公開すると、外部へ渡す前に書込み側が領域を再利用する設計になり得ます。本例は外部の`rd_valid && rd_ready`でだけ公開ポインターを進め、FIFO全体の容量を`DEPTH`エントリに保ちます。先読み用レジスタの分を容量へ足しません。

出力キューは`READ_LATENCY+2`エントリです。キューの空きだけでなく読出し待ちの予約も数え、将来返ってくるデータの置き場所を確保してから要求します。連続転送時は1読出しクロックにつき1画素を渡せます。レイテンシは空からの同期遅延や先読み待ちによって変わるため、TBは固定遅延で照合しません。

## RAM・FIFO・リセットの契約

RAMは1書込みポートと1読出しポートを持ち、別々のクロックで更新します。`READ_LATENCY=1/2`は読出し要求からRAM出力までの登録段数です。FIFOはその出力を次の読出しエッジで出力キューへ取り込みます。要求成立からFIFOのvalid提示までは、このキュー取込みの1段も加わります。RAMのデータ配列・データパイプはリセットせず、valid・ポインター・個数を初期化して古いデータを無効にします。

`WIDTH`は既定32、`DEPTH`は既定8で、深さは4以上の2のべき乗を前提にします。回帰では幅1／8／32、深さ4／8、読出し段数1／2を確認します。

書込みは`wr_valid && wr_ready`、読出しは`rd_valid && rd_ready`の各ローカル立上りで成立します。full時はメモリを書き換えません。出力停止中はvalidとデータを保持します。validがない間のデータは未規定で、比較しません。fullやemptyの解除には相手ポインターの同期遅延があり、TBの瞬時占有量と完全一致させません。

リセットは全体へ協調して非同期アサートし、各ドメインで2段同期して解除します。さらに相手側の解除完了を2段同期してから転送・先読みを許可します。RAMのvalidパイプも共通リセットで破棄します。解除時刻が違っても一方だけが古いFIFOの続きから転送しません。片側だけをリセットして継続する契約ではありません。

## 試験と波形

書込みが速い、読出しが速い、同周波数・同位相の同時エッジ、同周波数・位相差あり、幅8、幅1の6構成です。最初に満杯の未読データを作って協調リセットし、異なる世代のデータで再開します。再開後も一定期間読み出しを止め、full・先読み・出力停止・再開・空・複数回のポインター周回を確認します。入力bubbleと出力stallはseed付きで再現します。

期待値はTBが**受理した書込みデータ**を保存した配列です。読出し成立エッジ直前のデータを、その順序で比較します。クロックが同時に立ち上がっても、そのエッジの新規書込みが直ちに読出し可能になることはなく、同期と先読みを経た過去の受理データと比較します。Grayの1bit以下の変化は生成元でだけ検査し、同期先で更新が飛ぶことを禁止しません。

4種類の誤実装は、出力ビット反転、受信側の停止を無視した消費、RAM読出し値の欠落、fullを無視した書込みです。[要求と目標](requirements.json)の到達と、変異の検出を分けて記録します。

```sh
python3 examples/local-sync-ram-fifo/run.py --out artifacts/sync-ram-fifo-smoke
python3 examples/local-sync-ram-fifo/run.py --profile nightly --seed 42 --out artifacts/sync-ram-fifo-nightly
python3 examples/local-sync-ram-fifo/run.py --waves --out artifacts/sync-ram-fifo-wave
python3 -m unittest discover -s examples/local-sync-ram-fifo/tests -v
```

smokeは6構成×1 seed×128転送、nightlyは6構成×3 seed×512転送です。リセット前に破棄する転送は別扱いです。JUnitは18／30件、セルフテストは4件です。波形は`fast-write-lat1/seed17/trace.vcd`などで、`issue`、RAMの`valid_pipe`、`reserved`、`count`、外部valid/ready、公開ポインターと先読みポインターを追います。

各ケースの`trace.csv`に、読出しエッジのNBA後にTBが数えた瞬時占有量、読出し側の予約数・キュー数、valid/readyを記録します。`time_ps`はpsです。瞬時占有量はTBの観測値で、CDCを通さず実回路で利用できる値ではありません。書込み側のfullには読出し消費の同期遅延、先読みに使う書込みポインターにも同期遅延があります。

## ファイルと確認範囲

[sync_ram_async_fifo.sv](rtl/sync_ram_async_fifo.sv)がFIFOと先読み制御、[sync_dual_clock_ram.sv](rtl/sync_dual_clock_ram.sv)が同期RAM、[memory_reset_sync.sv](rtl/memory_reset_sync.sv)が解除同期、[sync_ram_fifo_tb.sv](tb/sync_ram_fifo_tb.sv)が自己判定TB、[run.py](run.py)が回帰計画です。

2026-11-20にIcarus Verilog 14.0開発版でsmoke／nightlyを実行しています。[実行記録](../../PROVENANCE.md#memory-integration-four)に版と結果を記載します。RTLシミュレーションではメタスタビリティを再現しません。CDC/RDC静的解析、同期FFの属性と配置、Grayバスの遅延・スキュー制約、実マクロの衝突窓・合成結果・STAは別途必要です。異クロックRAMの衝突条件は[AMDのメモリ資料](https://docs.amd.com/r/en-US/pg326-embedded-memory-generator/Collision-Behavior)にも記載されています。本例では領域の再利用を消費後に限定して衝突を避けますが、特定デバイスへの実装や他シミュレータは未確認です。
