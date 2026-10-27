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

深さ2／4、headは0から開始します。記述子を内部RAMから実際のAXI読出し応答として既存リング制御へ返し、コピーのAXI要求は外部RAMへ渡します。CPUが共有DRAM上の記述子を書き換える構成ではありません。キャッシュ保守・メモリバリア・実CPU命令は含みません。

| host_op | 操作 | 拒否条件・副作用 |
| --- | --- | --- |
| 1 | FREEへpublish | FREE以外・範囲外は拒否し、記述子を維持 |
| 2 | DONEをreclaim | DONE以外は拒否。受理するとFREEへ戻す |
| 3 | doorbell | 実行を有効化し、headのOWNEDを継続的に処理 |
| 4 | IRQ ACK | 通知をクリア。所有権・完了数は維持 |

ホストはvalidとreadyが成立するエッジでコマンドを完了し、その時点のerrorを検査します。doorbellで有効化した後は、headが未公開なら待ち、公開されると再開します。headを飛ばして後方のOWNEDを先に処理しません。

`retired`はエラーを含む返却済み記述子数です。各スロットのerrorを別に持ち、エラー時もDONEへ返します。次の記述子へ進み、回収・再公開で再利用できます。IRQは各返却でpendingになり、ACKまで保持します。

## 独立した検証

Pythonは公開するsrc・dst・wordsとエラーになる記述子から、最終メモリのチェックサムを計算します。SVは拒否応答、所有権、headと返却数、実AXIの番地・長さ・データ、全8192バイトも比較します。期待値をDUTのメモリから作りません。

固定ケースは公開前回収、不正コマンド・slot、二重公開・回収、処理中の追加、2／3周の再利用、不正な転送元、IRQ ACK、動作中の協調リセットです。各構成11目標。所有権の迂回、回収の欠落、head更新の誤り、実コピーのデータ破損の4変異を検出します。

```sh
python3 examples/local-dma-ownership/run.py --out artifacts/dma-ownership
python3 examples/local-dma-ownership/run.py --profile nightly
python3 -m unittest discover -s examples/local-dma-ownership/tests -v
```

[共通手順](../local-common/README.md)を使い、smokeは12操作列、nightlyは60列×3 seedに固定3列を加えます。JUnit14／18件、確認5件です。実行するコピーは各1〜4ワード・非重複領域で、任意の共有メモリ所有権プロトコルや動的tailポインターの検証ではありません。
