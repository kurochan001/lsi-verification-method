# 64ビットカウンターを32ビットAPBから一貫して読む

カウンターが動き続ける間の下位32ビットの桁上がりと、上下を別々に読むアクセスを組み合わせます。下位読出し時に上位を保存する、教材独自のスナップショット方式です。

## スナップショットの時点

```mermaid
sequenceDiagram
  accTitle: 下位読出し時の上位値を保存する
  accDescr: カウントが進んでも、次の上位読出しは下位と同じ時点の上位値を返す。
  participant H as APBホスト
  participant C as 64ビットカウンター
  participant S as 上位スナップショット
  H->>C: COUNT_LO読出し完了
  C-->>H: エッジ更新前の下位値
  C->>S: 同じ時点の上位値を保存
  Note over C: カウンターは桁上がりを含めて継続
  H->>S: COUNT_HI読出し完了
  S-->>H: 保存した上位値を返して消費
```

新しいCOUNT_LO読出しはスナップショットを上書きし、COUNT_HIは保存済み値を消費します。保存済み値がなければ現在の上位を返します。ホストはLO→HIの順で1組を読みます。複数ホストが同じスナップショットを競合して使う仕様ではありません。

| 番地 | 操作 | 動作 |
| --- | --- | --- |
| 0x00／0x04 | COUNT_LO／HI・RO | 上記のスナップショット読出し |
| 0x08／0x0C | LOAD_LO／HI・WO | LOを保持し、HI書込みで64ビットを一括反映 |
| 0x10／0x14 | COMPARE_LO／HI | LOを保持し、HI書込みで比較値を一括反映。読出しは確定済み値 |
| 0x18 | CONTROL | bit0=count enable、bit1=IRQ enable |
| 0x1C | STATUS | IRQ pending。bit0へのW1Cでクリア |

カウンターはenable中に1ずつ進み、64ビットで折り返します。次の値が確定済み比較値に等しくなるとpendingをセットします。LOAD_HI完了は加算と比較イベントより優先します。W1Cと比較イベントが同時ならイベント優先です。過去の比較値を設定しただけでは即座にIRQを出す仕様ではありません。

## 確認と実行

Pythonの広い整数と64ビットマスクから、APBの応答、カウンター、スナップショット、IRQを毎クロック予測します。下位の桁上がりを挟むLO／HI、64ビット全体の折返し、書込み途中の保持、比較とクリアの競合、リセットを検査します。

```sh
python3 examples/local-counter-snapshot/run.py --out artifacts/counter-snapshot
python3 examples/local-counter-snapshot/run.py --profile nightly
python3 -m unittest discover -s examples/local-counter-snapshot/tests -v
```

[共通手順](../local-common/README.md)を使います。APB待ち0／2の各10目標。smoke20操作列、nightly150列×3 seedを固定シナリオへ加えます。上位の生値読出し、下位だけの加算、クリア誤優先、LOAD_LOの早期反映の4変異です。JUnit14／18件、確認5件。実時間精度・クロック誤差・CPU命令の原子性・特定製品のタイマー互換性は対象外です。
