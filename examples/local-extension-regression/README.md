# RAL接続・順序制御・DMA・CRC・時刻・MBISTの7例

既存例で未対応だった部分を広げるローカル教材をまとめて実行します。GitLabの登録・CI設定・利用枠は使いません。

1. [生成RTL＋UVM RAL frontdoor](../local-generated-ral/README.md)
2. [AXI4の応答順序入れ替え](../local-axi-reorder/README.md)
3. [DMAリングの所有権](../local-dma-ownership/README.md)
4. [メモリ⇄Stream DMA](../local-stream-dma/README.md)
5. [パケットCRC](../local-packet-crc/README.md)
6. [64ビットカウンターのスナップショット](../local-counter-snapshot/README.md)
7. [MBIST・March C−](../local-mbist/README.md)

## 実行範囲と件数

```mermaid
flowchart TD
  accTitle: 7例の実行と集約
  accDescr: 共通シミュレーション6例と生成RALの実UVM例を別の環境で動かし、各子の完了を確認する。
  P["local-extension-regression"] --> C["core：6例・12構成"]
  P --> U["tools：生成RAL frontdoor"]
  C --> I["Icarus・独立モデル・変異検出"]
  U --> V["SystemRDL・Verilator・実UVM"]
  I --> E["子の詳細JUnitと証跡"]
  V --> E
  E --> G["親7ゲートで成功・完了を確認"]
```

| 区分 | smoke JUnit | nightly JUnit |
| --- | --- | --- |
| 共通シミュレーション6例 | 84 | 108 |
| 生成RALの実接続 | 15 | 19 |
| 直下の子の合計 | 99 | 127 |
| 親の集約ゲート | 7 | 7 |

親と子を重複加算しません。通常カバレッジは正常終了し、予定した比較・件数を満たした通常ケースだけを使います。各例4種類の負の試験を持ちますが、生成RALの1件はモデル側の診断で、全件をRTL変異検出率へまとめません。

## 準備と実行

coreはPython 3.10以上・Icarusを使います。toolsにはVerilator 5.052・C++20、[外部UVMライブラリ](../local-uvm/README.md)と[SystemRDL用Python](../local-register-spec/README.md)を準備します。

```sh
python3 examples/local-extension-regression/run.py --stage core --out artifacts/extension-core
python3 examples/local-extension-regression/run.py \
  --uvm-home /tmp/lsi-uvm-library/1800.2-2020.3.2 \
  --rdl-python /tmp/lsi-rdl-venv/bin/python --out artifacts/extension-all
```

同じ引数へ`--profile nightly`と新しい`--out`を指定するとnightlyです。`--stage tools`は生成RALだけです。`--child-timeout`は子1回帰の上限で、既定1800秒です。選択しなかった例は合格にしません。ツールの自動インストールは行わず、既存出力先は上書きしません。

各子の入力・ソースハッシュ・ツール版、正常／負の結果、ログ、VCDを保存します。親では予定数・完了・成功と、一意で空でない結果IDを照合します。

確認テストは6回路各5件・生成RAL判定2件・親4件の計36件です。

```sh
python3 -m unittest discover -s examples/local-extension-regression/tests -v
python3 -m unittest discover -s examples/local-generated-ral/tests -v
```

回路ごとの確認コマンドと、教材で採用した仕様・対象外は各READMEを参照してください。任意のAXI実装・CPU・実メモリ・製品の正しさを一括で保証する計画ではありません。

## 実行確認

2026-10-27に全7例のsmoke／nightlyが成功しました。親JUnitは各7件、子は99／127件です。新規確認36件もすべて成功し、各マニフェストのソースハッシュと使用UVMライブラリsrcのハッシュを現行ファイルと照合しました。過去の407件は今回の新規実行へ加算せず、確認テスト全体の計画は443件です。
