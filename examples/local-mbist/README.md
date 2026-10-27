# March C−のMBISTとデジタル故障注入

1ビットのメモリセル8／16個を使い、March C−の各読書き、最初の不一致アドレス、試験完了と操作数を検証します。通常機能のECCとは異なり、記憶セルへの故障とテストアルゴリズムの検出を扱う教材です。

## 試験回路と独立モデル

```mermaid
flowchart TD
  accTitle: Marchアルゴリズムと故障メモリの照合
  accDescr: RTLコントローラーの実操作を予定列と比較し、故障モデルの読出しを与えて結果を確認する。
  P["Python：仕様のMarch操作列・故障モデル"] --> E["予定操作・最初の失敗を計算"]
  C["RTL MBISTコントローラー"] --> M["SVの故障メモリモデル"] --> C
  C --> V["実操作・失敗位置・完了を比較"]
  E --> V
```

| 順序 | アドレス方向 | セルごとの操作 |
| --- | --- | --- |
| 1 | 昇順 | w0 |
| 2 | 昇順 | r0、w1 |
| 3 | 昇順 | r1、w0 |
| 4 | 降順 | r0、w1 |
| 5 | 降順 | r1、w0 |
| 6 | 昇順 | r0 |

r0／r1は期待値0／1の読出し、w0／w1は書込みです。Nセルで10N回、メモリreadyによる待ちは操作数に含めません。不一致後も全操作を続け、最初の失敗位置を保持します。startはアイドル時だけ受理し、doneは次startまたはリセットまで保持します。試験はメモリ内容を破壊します。

## 故障モデルと判定

SVのモデルは、選んだセルの0／1固着、片方向への遷移阻止、2番地の別名化、選んだaggressorの0→1書込みによるvictim反転を注入します。結合故障はこの特定のモデルで、すべての結合故障を表しません。Pythonもセル配列へ故障を適用し、最初に不一致となるアドレスを独立に求めます。

SVではコントローラーの各受理操作を、Pythonの予定列と照合します。エラー通知だけでなく、10N操作、方向・番地・書込み値、first-fail、途中リセットからの再実行も要求します。9目標、失敗通知抑止・失敗番地破損・書込み値破損・早すぎる完了の4変異です。注入故障は通常の検証対象、変異は検証環境の検出力確認として分けます。

```sh
python3 examples/local-mbist/run.py --out artifacts/mbist
python3 examples/local-mbist/run.py --profile nightly
python3 -m unittest discover -s examples/local-mbist/tests -v
```

[共通手順](../local-common/README.md)を使います。smoke20試行、nightly120試行×3 seedに固定8試行を加えます。JUnit14／18件、確認5件。March C−の参考は[Microchip AN1229](https://ww1.microchip.com/downloads/en/AppNotes/01229B.pdf)です。アルゴリズムの一般的な記法を参考に新規作成し、製品ライブラリは転載しません。実SRAM、ワード指向への変換、ATPG、製造故障全体の検出率、機能安全認証の評価は含みません。
