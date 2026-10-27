# I²CのACK・Repeated START・クロックストレッチを検証する

7ビットアドレス`0x42`のI²Cターゲットと、独立したコントローラーBFMを使うローカル教材です。1バイトの書込み・読出し、アドレス不一致、データNACK、Repeated START、クロックストレッチ、転送中リセットを実際のSCL／SDAで検査します。

## 1. この回路の仕様

SCLとSDAは、RTLとBFMが0またはZだけを駆動するオープンドレイン信号です。テストベンチの`tri1`でプルアップを表現します。RTLは別の`clk`でSCL／SDAを2段同期してエッジ・START・STOPを検出します。同期アクティブLowリセットで内部バイトを0にし、両信号を解放します。

| 操作 | バス上の手順とこの教材の動作 |
| --- | --- |
| 書込み | START、アドレス＋W、ACK、データ1バイト、ACK、STOP。データACKのSCL立上りを同期検出したときに値を保持 |
| 読出し | START、アドレス＋R、ACK、保持値1バイト、コントローラーNACK、STOP |
| 書込み後の読出し | 書込みのデータACK後、STOPを挟まずRepeated STARTを発行し、同じアドレスへRを送って読み返す |
| アドレス不一致 | NACKし、内部値を変更しない |
| データ受付拒否 | 教材用の`reject_data=1`でデータにNACKし、前の値を保持 |
| ストレッチ | ACKを返す直前のSCL立下りの同期検出後、指定した`stretch_cycles`だけSCLをLowに保持 |
| 転送中リセット | アドレスACK後、データ上位4ビットまで送ってリセット。途中のデータは保持せず0へ戻す |

レジスタアドレスの転送はなく、内部値は1バイトだけです。MSBから送り、1回の読出しは必ずコントローラーNACKで終了します。連続複数バイト、10ビットアドレス、複数コントローラーの仲裁、General Call、バスクリア、ノイズフィルターは対象外です。

バスのSTART／STOP、ACK／NACK、Repeated START、ストレッチの考え方は[NXP UM10204 Rev.7.0](https://www.nxp.com/docs/en/user-guide/UM10204.pdf)の3.1.4〜3.1.10を参照しています。内部値の更新、拒否入力、リセット、同期段数は教材独自の仕様です。

## 2. 期待値と検査

Pythonの参照モデルは、バス状態機械を再実装せず、**成功した書込みだけで更新する1バイトの期待値**を保持します。アドレス不一致・データNACKでは保持、途中リセットでは0とします。

BFMは、DUT内部の状態を期待値に使わず、8ビットと9番目の応答クロックを自ら生成します。SCLを解放しても線がLowならHighを待ち、許容時間を超えたら失敗させます。SDAのACK値を照合した後、ストレッチの有無と許容待ち時間を比較します。線の解放直後はデルタサイクルで値が確定するのを待ち、それをストレッチとして数えません。

読出しデータはSDAから実際に組み立て、Pythonの期待値と比較します。内部保持値も操作前後に比較し、START／STOPやリセット後の信号解放も検査します。SCL／SDAのアナログ立上り、容量やsetup／holdの実測はモデル化しません。

固定11操作で、0／全1／交互／LSB／MSBの読戻し、STOPを挟む書込みと読出し、アドレス不一致、データ拒否、途中リセット、復帰を実行します。正常時の件数は書込み7、読出し7、ターゲットNACK 2、リセット1、ストレッチ12です。1操作に複数のアドレス・データ応答があるため、ストレッチ数と操作数は一致しません。

追加ランダム操作では、書込み、書込み＋Repeated START読出し、読出し、不一致、拒否、途中リセットを選び、データとストレッチ0／20／28クロックを変えます。末尾に正常な書込み・読戻しを追加します。[要求カタログ](requirements.json)は4要求・18目標で、操作数と種別別の完了件数も照合します。

## 3. 意図的な誤実装

| 番号 | 誤実装 | 期待する検出ラベル |
| --- | --- | --- |
| 1 | 読出し時、SDAへ送るデータのLSB反転 | I2C_DATA |
| 2 | 指定されたストレッチを行わない | I2C_STRETCH |
| 3 | 異なるアドレスにもACKする | I2C_ACK |
| 4 | 転送途中のRepeated STARTを無視する | I2C_ACK |

変異1は内部値を正常に保ったまま送信ビットを壊すため、内部値だけの比較では足りないことも確認できます。予定ラベルと非ゼロ終了を確認し、変異の観測は通常の18目標に算入しません。

## 4. 実行

[共通の準備・証跡](../local-common/README.md)に従い、リポジトリのルートから実行します。

```sh
python3 examples/local-i2c/run.py --out artifacts/i2c-smoke
python3 examples/local-i2c/run.py --configuration half12 --seed 42 --iterations 100 --out artifacts/i2c-seed42
python3 examples/local-i2c/run.py --profile nightly --out artifacts/i2c-nightly
python3 -m unittest discover -s examples/local-i2c/tests -v
```

構成名は`half8`と`half12`です。BFMのSCLの通常の半周期を、ベースクロック8／12個分とします。シミュレーションではclk=10ns周期で動かしますが、この時間尺度でStandard-modeなどの電気的タイミングへの適合を確認したとは扱いません。

smokeは32ランダム操作×1 seed、nightlyは256×3 seedを実行し、各seedの末尾に正常操作を1つ追加します。`checks`は操作数です。構成当たりのJUnitはsmoke **7件**、nightly **9件**（固定1＋ランダム1／3＋変異4＋ゲート1）。2構成の合計は**14／18件**です。

```sh
python3 examples/local-i2c/run.py --configuration half8 --demo-bug 1 --out artifacts/i2c-intentional-failure
```

このコマンドは通常回路にも送信データの不具合を入れるため、終了コード1と`I2C_DATA`による失敗が期待結果です。

## 5. 実行確認

2026-10-27にPython 3.14.7、Icarus Verilog 14.0開発版で2構成のsmoke／nightly、各18目標・4変異、確認テスト5件が成功しました。GitLabへの追加・CI実行は行っていません。これはデジタル動作の教材で、実機やI²C規格全体の適合性を示す結果ではありません。
