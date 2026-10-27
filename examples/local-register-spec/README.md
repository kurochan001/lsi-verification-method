# SystemRDLからRTL・Cヘッダー・RALを生成して照合する

`registers.rdl`を実際のSystemRDLコンパイラーでエラボレーションし、独自の小さなexporterでAPB RTL、Cヘッダー、UVM RALを生成します。生成物は実行先に保存し、別に手書きした`contract.json`と照合します。GitLabは使いません。

## 原本と生成物の検査

教材の原本は、0x00の8ビットCONFIG（RW、reset 0x12）、0x04の32ビットID（RO、0x52444c31）、0x08の4ビットPENDING（W1C、reset 0）です。PENDINGでは同一エッジのイベントをクリアより優先します。

- コンパイラーの番地・幅・reset・アクセス属性を、別の契約ファイルと比較します。
- 生成RTLをIcarusで実行し、手書きした番地・期待値モデルで読書き、部分フィールド、RO拒否、W1C競合、待ち0／2を確認します。
- 生成CヘッダーをC11のプログラムへ取り込み、9個の番地・マスク・reset定数を照合します。
- 生成RALをUVMライブラリとコンパイルし、実オブジェクトの番地・フィールド幅・アクセス属性・resetを照合します。ここではRALのfrontdoorで生成RTLを駆動せず、RTLの機能検証とは別に行います。

原本のresetを誤らせて全ビューを生成し直し、生成物同士が同じ誤りを共有しても独立契約が拒否することを確認します。契約ファイル自体の正しさは仕様レビューで確認する必要があります。

## 対応する範囲

exporterは`cfg`・`idreg`・`pending`という3レジスタ、32ビットのスカラー、各1フィールド、LSB 0、RW／RO／W1C、明示的な整数resetという限定した形式です。配列、階層、多フィールド、RC、singlepulseなどの未対応属性は拒否します。ハードウェア側はcfg／idregが読出し専用、pendingが本教材のイベント更新だけに対応し、追加の属性を読み飛ばしません。汎用SystemRDL exporterではありません。

## 準備と実行

```sh
python3 -m venv /tmp/lsi-rdl-venv
/tmp/lsi-rdl-venv/bin/python -m pip install -r examples/local-register-spec/tools-requirements.txt
/tmp/lsi-rdl-venv/bin/python examples/local-register-spec/run.py \
  --uvm-home /tmp/lsi-uvm-library/1800.2-2020.3.2 --out artifacts/register-spec
/tmp/lsi-rdl-venv/bin/python -m unittest discover -s examples/local-register-spec/tests -v
```

Python 3.10以上、systemrdl-compiler 1.30.1、Icarus、Cコンパイラー、Verilator 5.052、[外部のUVMライブラリ](../local-uvm/README.md)を使います。Python依存はrequirementsへ固定しています。`--profile nightly`はRTLランダム操作を24×1 seedから150×3 seedへ増やします。固定10操作は各実行に含みます。

reset誤り・フィールドマスク誤り・W1C優先順位のRTL変異3件、Cヘッダーの番地破損、構築したRALのreset破損も検出します。後2件と原本の誤りの診断はRTL変異率へ加えません。予定ラベルと非ゼロ終了を要求します。

生成ファイルとハッシュ、使用ライブラリsrcのハッシュ、コンパイラー版、入力、ビルド・実行ログ、RTL波形、JUnitを保存します。CとRALの検査は定数・モデルの検査で、波形を保存する実RTLの試験とは区別します。JUnitは16／20件、確認テストは5件です。

[SystemRDL標準](https://www.accellera.org/downloads/standards/systemrdl)、[コンパイラーAPI](https://systemrdl-compiler.readthedocs.io/en/stable/api/compiler.html)、[プロパティの既定値](https://systemrdl-compiler.readthedocs.io/en/stable/properties.html)を参照しています。外部ライブラリのソースはリポジトリへ転載していません。
