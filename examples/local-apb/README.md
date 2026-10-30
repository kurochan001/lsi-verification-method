# APBレジスタを検証する

32ビットのAPBレジスタ回路を、Pythonで作る入力列とSystemVerilogの参照モデルで検証する例です。Icarus Verilogで動くため、商用シミュレータは不要です。境界テスト、seed付きランダム転送、3種類の意図的な不具合、要求・カバレッジの判定を実行します。

## SETUPから完了までの照合順序

SETUPと待ち中は状態を維持し、ACCESSの完了エッジでだけ正常書込みを反映します。

```mermaid
flowchart LR
  accTitle: SETUPから完了までの照合順序
  accDescr: SETUPと待ち中は状態を維持し、ACCESSの完了エッジでだけ正常書込みを反映します。
  S["SETUP：要求を提示"] --> A["ACCESS：要求を保持"] --> R{"PREADY？"}
  R -- "0" --> A
  R -- "1" --> C["読出し・エラー応答を照合"] --> U["正常書込みとイベントの更新を照合"]
```

PENDINGはイベントとW1Cが同時ならイベント優先です。エラー書込みの無副作用も通常ケースの比較に含めます。

## 1. 対象とレジスタ仕様

APB3で導入されたPREADY・PSLVERRを含む信号を使います。アドレス幅8ビット、データ幅32ビット、単一スレーブです。PSTRB・PPROT、複数スレーブの選択、UVM RALは実装していません。APB規格全体への適合性を認定するテストではありません。

| バイトアドレス | 名前 | アクセス | 動作 |
| --- | --- | --- | --- |
| `0x00` | CONFIG | RW | 32ビットの設定値。リセット値0 |
| `0x04` | ID | RO | 固定値`0x41504233`。書込みはエラー |
| `0x08` | PENDING | W1C | 下位4ビットのイベント保持。1を書いたビットをクリア。上位28ビットは読出し0、書込み無視 |
| その他 | 未割当・非整列 | エラー | 読出し値0、書込みの副作用なし |

この周辺回路では、次の動作を仕様として定めています。

- `rst_n=0`をクロック立上りで取り込む同期リセットで、CONFIG・PENDINGと待ち状態を初期化します。リセット中は転送を受理しません。
- SETUP（`PSEL=1, PENABLE=0`）を1サイクル置き、ACCESS（両方1）へ進みます。`PSEL && PENABLE && PREADY`が成立する立上りで転送を完了します。
- `WAIT_CYCLES=0/1/3`により、各転送のACCESSを0/1/3サイクル待たせます。エラー転送にも同じ待ち時間を適用します。
- 設定値やW1Cの更新は完了時のみです。SETUP・待ち状態中にバス書込みの副作用は発生しません。
- 外部入力`events[3:0]`は毎クロック取り込みます。同一ビットのイベントとW1Cが同時なら**イベントを優先して1を保持**します。読出し値は完了エッジ直前の状態です。
- PSLVERRは完了サイクルのみ1にし、その他は0にします。エラー転送ではCONFIG・PENDINGをバス操作で変更しません。ただし独立したイベントの取り込みは継続します。
- 同一スレーブへの連続転送ではPSELを1のまま保持でき、転送ごとにPENABLEを0に戻してSETUPを挟みます。

APBのエラー応答が常に「副作用なし」を保証するわけではありません。エラー時の状態保持、読出し値0、W1Cとイベントの優先順位、同期リセットは**この説明用回路の仕様**です。プロトコルの参照先は[Arm AMBA APB Protocol Specification（IHI 0024）](https://developer.arm.com/documentation/ihi0024/latest/)です。

## 2. 何を判定するか

| 検査 | 比較・観測 |
| --- | --- |
| 読出し・書込み | CONFIG、ID、PENDING、未割当、非整列の5分類×読出し／書込み。応答と状態を比較 |
| 待ち状態 | 参照モデルの経過サイクルからPREADYを予測。待ち時間の不足・超過を検出 |
| 副作用 | CONFIG・PENDINGの外部出力を毎クロック比較し、早すぎる更新やエラー時の更新を検出 |
| W1C | 参照モデルがビットごとにクリアとイベントを適用。ゼロ書込み、全クリア、同一ビットの競合を確認 |
| リセット | IDLE・SETUP・ACCESSでのリセットと、その後の読出しを確認。リセット中はPREADY・PSLVERRが0で、転送を完了させないことも検査 |
| マスターの入力列 | SETUPからACCESSへの遷移、待ち状態中の要求保持、連続転送間のSETUPを監視 |

CONFIG・PENDINGの出力は、説明用回路の機能出力兼観測点です。バス読出しだけでは次の書込みで隠れる一時的な誤更新も、毎クロックの比較で確認します。DUTはマスク式、参照モデルはビットごとの更新でW1Cを計算します。これは手続き的チェッカーであり、SVAやcovergroup DBを使う例ではありません。

`requirements.json`は、アドレス分類×操作10目標、代表データ3目標、W1C 3目標、リセット3目標、連続転送1目標、待ち状態1目標を定義します。wait=0では待ち状態を明示的に除外して**要求5件・20目標**、wait=1/3では**要求6件・21目標**です。各構成を別々に判定し、他構成の観測で補完しません。

カバレッジは、そのサイクルの比較に合格した後に`COVER`として出力します。正常ケース全体が完了し、予定したチェック数も一致した場合だけ集計へ採用します。変異ケースは通常機能の目標達成には数えません。この目標数は説明用に選定した範囲であり、製品レジスタ仕様の全項目を網羅した値ではありません。

## 3. ローカルで実行する

Python 3.10以上とIcarus Verilogの`iverilog`・`vvp`を用意し、リポジトリのルートから実行します。

```sh
python3 examples/local-apb/run.py --wait 1
python3 -m unittest discover -s examples/local-apb/tests -v
```

smokeは境界1ケース、ランダム1 seed×200転送、変異3ケース、カバレッジ判定1件で、**JUnit 6件／構成**です。nightlyはランダムを3 seed×2,000転送へ拡張し、**JUnit 8件／構成**になります。`--transactions`は1 seedあたりのランダム転送数で、SETUP・待ち・リセットなどを含むクロック数とは異なります。

```sh
python3 examples/local-apb/run.py --wait 3 --profile nightly --seed 73
# 短い再現実行。出力先は毎回新しいディレクトリを指定する
python3 examples/local-apb/run.py --wait 1 --seed 73 --transactions 40 --out artifacts/apb-replay-73
```

入力生成はseedで再現できます。厳密な再実行には`manifest.json`のソースハッシュ、ツール版、全入力列も合わせます。ランナーは[IRQ例のプロセス実行・終了判定処理](../local-irq-cdc/run.py)を利用するため、`local-apb`単独ではなく`examples`一式を保持してください。

## 4. 意図的な不具合で検出力を確認する

| `--demo-bug` | 不具合 | 予定する検出ラベル |
| --- | --- | --- |
| 1 | CONFIGをSETUPで書き換える | `APB_STATE` |
| 2 | 同時発生時にイベントよりW1Cを優先する | `APB_W1C` |
| 3 | エラー書込みでCONFIGを変更する | `APB_ERROR_SIDE_EFFECT` |

通常リグレッションでも3種類の変異を別々に実行し、所定の比較で検出できることを要求します。下記は正常ケースにも不具合を入れ、終了コード1とJUnitのfailureを確認するデモです。

```sh
python3 examples/local-apb/run.py --wait 1 --demo-bug 2
```

変異が生き残る場合は失敗です。ビルド失敗、タイムアウト、別のエラー、完了記録のない終了は、変異検出の成功にしません。ランナーの12テストで3構成、3種類の不具合、入力の再現、欠落目標、変異からのカバレッジ混入防止、異常終了、既存証跡の上書き防止を確認します。

## 5. 構成ごとの実行と証跡

待ち状態0／1／3の3構成を、`--wait`で1構成ずつ独立に実行します。失敗デモは`--demo-bug 1/2/3`、seedは`--seed`で選べます。ランナーは失敗を非0の終了コードで返し、JUnitは結果表示に使います。

出力先（既定は`artifacts/apb-local-日時/`）へ、次を保存します。

- `manifest.json`：設定、seed、予定ケース、全クロック入力、ソースハッシュ。
- `tools.json`・`builds.json`：ツール版、ビルドコマンドと結果。
- ケース別ディレクトリ：`vectors.txt`、ログ、VCD波形、`result.json`。
- `coverage.json`・`summary.json`・`junit.xml`：要求の成否、未達・除外、完了・変異検出の件数。

## 6. 実行確認

2026-10-26にPython 3.14.7・Icarus Verilog 14.0開発版でランナー12テストと、wait=0/1/3のnightly全構成を確認しました。各構成で20/20または21/21目標を達成し、3種類の変異を検出しました。nightlyは既定seed 17〜19を各2,000転送実行しています。

公開デモの[MR !4](https://gitlab.com/kurochan001/lsi-verification-method-ci-demo/-/merge_requests/4)で、[CI #2988642917](https://gitlab.com/kurochan001/lsi-verification-method-ci-demo/-/pipelines/2988642917)の全16ジョブ成功、JUnit 108件・失敗／エラー0件を確認しました。APBの3ジョブはIcarus Verilog 11.0で実行され、保存済み`summary.json`と`manifest.json`でも各構成の目標達成、3種類の変異の検出、予定5ケースの完了と対象コミット`d623c595`を確認しています。APB追加分のJUnitは18件、ランナーのセルフテストは別枠の12テストです。

確認したGitLab実行はsmokeです。nightlyのAPB 3構成はローカルで確認しており、全例を含むscheduleの129件をGitLabで実行した結果ではありません。その後、MR !4はmainへマージされ、[mainのCI #2988663611](https://gitlab.com/kurochan001/lsi-verification-method-ci-demo/-/pipelines/2988663611)も全16ジョブ・JUnit 108件で成功しています（2026-10-26確認）。

設計例を製品へ適用する場合は、実際のレジスタ仕様、リセット方式、アクセス属性、バイトイネーブル、割り込みとの接続、ソフトウェアの操作順を追加してください。[機能間のクロス検証](../../docs/method/feature-interaction-verification.md)と[継続リグレッション](../../docs/method/continuous-regression.md)も参照してください。

この回路へ割り込み出力を接続する[APBと割り込みの結合検証例](../local-apb-irq/README.md)も用意しました。マスク、W1C、イベント、複数要因を組み合わせた検証へ進めます。
