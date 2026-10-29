# DMAリングの所有権・完了返却・再利用を結合検証する

ホスト側の公開・回収コマンド、内部の記述子RAM、既存の[リング制御](../local-descriptor-dma/README.md)・[DMAコア](../local-dma/README.md)・[AXI4 RAM](../local-axi4/README.md)を接続します。同じスロットの二重公開・二重実行を防ぎ、処理中の記述子追加と周回後の再利用を確認する教材です。

## 所有権とホスト操作

```mermaid
stateDiagram-v2
  accTitle: 記述子スロットの所有権
  accDescr: ホストが公開し、DMAが取得・完了して、ホストが回収するまで再公開を禁止する。
  FREE --> OWNED: publishでsrc・dst・wordsを格納
  OWNED --> BUSY: headの記述子を実行
  BUSY --> DONE: 正常・エラー完了を記録
  DONE --> FREE: reclaim
```

深さ2／4、headは0から開始します。記述子を内部RAMから実際のAXI読出し応答として既存リング制御へ返し、コピーのAXI要求は外部RAMへ渡します。記述子読出しはID=0、データ読出しはID=1で区別するため、外部データの転送元が内部記述子の番地範囲（6144〜6144＋16×深さ−1）と重なってもコピーできます。CPUが共有DRAM上の記述子を書き換える構成ではありません。キャッシュ保守・メモリバリア・実CPU命令は含みません。

| host_op | 操作 | 拒否条件・副作用 |
| --- | --- | --- |
| 1 | FREEへpublish | FREE以外・範囲外は拒否し、記述子を維持 |
| 2 | DONEをreclaim | DONE以外は拒否。受理するとFREEへ戻す |
| 3 | doorbell | 実行を有効化し、headのOWNEDを継続的に処理 |
| 4 | IRQ ACK | 通知をクリア。所有権・完了数は維持 |

ホストはvalidとreadyが成立するエッジでコマンドを完了し、その時点のerrorを検査します。doorbellで有効化した後は、headが未公開なら待ち、公開されると再開します。headを飛ばして後方のOWNEDを先に処理しません。

`retired`はエラーを含む返却済み記述子数を示す8ビットのカウンターで、256で折り返します。各スロットのerrorを別に持ち、エラー時もDONEへ返します。次の記述子へ進み、回収・再公開で再利用できます。IRQは各返却でpendingになり、ACKまで保持します。

## 完了通知とスロット回収の違い

IRQ ACKは通知の解除、reclaimはスロットの回収です。以下は他の完了・ACKが重ならない単一スロットの例で、doorbellによる実行は有効になっているものとします。

```mermaid
sequenceDiagram
  accTitle: 公開から完了通知・回収・再公開まで
  accDescr: DMA完了後も所有権はDONEで保持され、IRQ ACKだけでは再公開できない。
  participant H as ホスト
  participant R as 所有権リング
  participant D as 既存DMA・RAM
  H->>R: publish(src, dst, words)
  Note over R: FREE → OWNED
  R->>D: headの記述子でコピー開始
  Note over R: OWNEDから<br/>BUSYへ
  D-->>R: 正常またはエラー完了
  Note over R: BUSY → DONE<br/>retiredを加算<br/>IRQセット
  H->>R: IRQ ACK
  Note over R: IRQ解除<br/>DONEを維持
  H->>R: reclaim
  Note over R: DONE → FREE
  H->>R: 次の記述子をpublish
  Note over R: FREE → OWNED
```

| 確認時点 | スロットの所有権 | IRQ | 再publish |
| --- | --- | --- | --- |
| 初期化後 | FREE | 0 | 受理する |
| 公開後・取得前 | OWNED | 0 | 拒否する |
| コピー中 | BUSY | 0 | 拒否する |
| 完了後 | DONE | 1 | 拒否する |
| IRQ ACK後 | DONE | 0 | 拒否する |
| reclaim後 | FREE | 0 | 受理する |

エラー完了でもDONEへ返します。IRQだけで成否を決めず、スロットのerrorとコピー結果を照合します。実行を有効にした後は、FREEへ戻しただけでは再実行せず、再publishされたOWNEDを取得します。

## 独立した検証

Pythonは公開するsrc・dst・wordsとエラーになる記述子から、最終メモリのチェックサムを計算します。SVは拒否応答、所有権、headと返却数、実AXIの番地・長さ・データ、全8192バイトも比較します。期待値をDUTのメモリから作りません。初期データには上位アドレスも混ぜ、256バイト離れた領域が同一パターンになってコピー漏れを見逃すことを防ぎます。

固定ケースは公開前回収、不正コマンド・slot、二重公開・回収、処理中の追加、2／3周の再利用、不正な転送元、IRQ ACK、動作中の協調リセット、転送元と内部記述子の番地範囲の重なりです。各構成11目標。所有権の迂回、回収の欠落、head更新の誤り、実コピーのデータ破損の4種類の変異を検出します。

```sh
python3 examples/local-dma-ownership/run.py --out artifacts/dma-ownership
python3 examples/local-dma-ownership/run.py --profile nightly
python3 -m unittest discover -s examples/local-dma-ownership/tests -v
```

[共通手順](../local-common/README.md)を使い、smokeは12操作列、nightlyは60列×3 seedに固定4列を加えます。JUnit14／18件、確認6件です。実行するコピーは各1〜4ワード・非重複領域で、任意の共有メモリ所有権プロトコルや動的tailポインターの検証ではありません。
