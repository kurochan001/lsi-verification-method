# 複数クロック・個別リセットを扱う上位UVM環境

独立したクロックで動く送信側と受信側を、一つの上位virtual sequenceから協調させます。片側だけのリセットでも受理済み要求を取り消し、リセット前の応答を復帰後に受け付けないことを確認します。[単一クロックのagent協調](../local-uvm-coordination/README.md)、[子環境と上位RAL](../local-uvm-hierarchy/README.md)の次の演習です。

## 1. 回路の契約

`reset_mailbox`は、同時に1件だけ未完了要求を持つbundled-dataのreq／ack回路です。送信側で`src_valid && src_ready`を受理し、受信側で`dst_valid && dst_ready`が成立すると、同じIDと`src_data ^ 8'h3c`を完了として観測します。IDは検証時の追跡用メタデータで、実行中はリセットをまたいで再利用しません。

| 条件 | 要求する動作 |
| --- | --- |
| 受信側が待ち状態 | valid・ID・データを保持 |
| 一方または両方のresetをアサート | チャネル全体を破棄し、未完了要求を取消。古い応答を再開しない |
| ローカルresetを解除 | 各ドメインで2段同期して`up`を立てる |
| 両端復帰 | チャネル用resetも各ドメインで同期解除し、相手の`up`を同期してから転送を再開 |

未完了要求をreset時に保持して後で再送する仕様ではありません。要求の受理、正常完了、取消を別に数えます。

## 2. 環境と観測時刻

```mermaid
flowchart LR
  accTitle: 複数クロックのUVM観測と取消
  accDescr: 上位sequenceが送信、受信ready、個別resetの三つのagentを動かす。各monitorは実際の受理とreset時刻を記録し、スコアボードが時刻とリセット世代で期待値を管理する。
  V["上位virtual sequence"] --> S["送信agent<br/>src_clk"]
  V --> D["受信ready agent<br/>dst_clk"]
  V --> R["個別reset agent"]
  S --> M["mailbox DUT"]
  D --> M
  R --> M
  S -. "受理時刻・ID・入力" .-> B["時刻順のscoreboard<br/>期待値とreset世代"]
  D -. "完了時刻・ID・出力" .-> B
  R -. "resetの実変化" .-> B
```

各monitorは通知前に新しい観測オブジェクトへ実際のエッジ時刻を保存します。scoreboardは最大2nsの通知遅延より長い3nsを待ち、時刻順に処理します。同じ時刻ではreset、送信受理、受信完了の順です。二つのmonitorの通知遅延を入れ替えても、正規化した観測列と最終結果が同じことをPythonでも確認します。この待ち時間は本例で固定した通知遅延に対する設計で、無制限な遅延を扱う一般的な同期機構ではありません。

resetのアサートで世代を進め、期待値・受理時刻・世代をまとめて取り消します。取消済みIDや未知のIDの応答は`MC_STALE`です。全観測時点で次の台帳を検査します。

`受理数 = 完了数 + 取消数 + 未完了数`

Python側も生の`MC_OBS`記録と`MC_ISSUED`から独立に同じ契約を再構成します。刺激を発行しただけでは受理と数えず、実際のハンドシェイクと照合します。

## 3. 実行

[基本UVM例の準備](../local-uvm/README.md#ライブラリの準備)でAccellera UVM 2020.3.2を取得してから実行します。Python 3.10以上、POSIX、Verilator 5.052、C++20コンパイラー、makeが必要です。

```sh
python3 examples/local-uvm/setup_uvm.py --out artifacts/toolchains/uvm-library
python3 examples/local-uvm-multiclock/run.py \
  --uvm-home artifacts/toolchains/uvm-library/1800.2-2020.3.2 \
  --out artifacts/uvm-multiclock
```

すでにUVMを準備している場合は、取得を省略し`--uvm-home`へ実際の場所を指定します。`--profile nightly`で通常のseedを1個から3個へ、追加要求を40件から160件へ増やします。既存のディレクトリは上書きしません。

| 構成・判定 | 内容 |
| --- | --- |
| クロック条件0 | src周期6ns、dst周期10ns、位相差0。正エッジが同時になる場合を含む |
| クロック条件1 | src周期10ns、dst周期6ns、dst開始位相1ns |
| 通知順序 | source／destinationの通知遅延1ns／2nsを入れ替える2構成 |
| reset試験 | 送信側のみ、受信側のみ、両端から送信側先に解除、受信側先に解除 |
| 正常実行 | 4構成×seed。各実行で受理`17+追加要求数`、完了`13+追加要求数`、取消4、世代4、未完了0 |
| 変異 | データ破損、相手resetの無視、同期解除の迂回を全4構成で検出 |
| 検査の診断 | source観測停止、reset観測停止、保持検査への故障注入を全4構成で検出 |

JUnitはsmoke 32判定／nightly 44判定です。ネイティブSVAの9 coverについて、ラベル・ソース・階層・DB件数とactionの件数を照合し、全正常実行で到達を要求します。UVMの版と完了件数、ERROR／FATAL 0、既知のDPI無効化に関するWARNING 2件も確認します。ログ、VCD、coverage DB、UVMソースのハッシュ、予定と実行結果を保存します。

## 4. 対象外

resetの刺激は半整数ns、クロックのエッジは整数nsに置き、同一シミュレーション時刻でのresetとクロックの競合を除外しています。両クロックは常時動作し、未完了要求は最大1件です。任意のクロック停止、多数のID、タイムスタンプの折返し、全位相・全比率の試験ではありません。

このRTLと論理シミュレーションだけで、物理的なメタスタビリティ、束ねたデータの到着制約、MTBF、CDC/RDCの構造、resetのrecovery／removalを保証しません。実装時は同期器の属性・配置、タイミング制約、CDC/RDC解析を別に確認します。[領域の点検](../../docs/method/verification-gap-review.md#4-cdcrdcとクロック制御)も参照してください。
