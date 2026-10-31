# コードカバレッジの未達を追加試験で補う

4状態のコマンド実行回路を使い、Verilatorの行・分岐・式・toggle・FSMを実測する例です。基礎試験の未達を確認し、追加試験のDBと統合して再判定します。計測対象とポイント集合を固定し、機能比較に合格した実行だけを採用します。考え方は[コードカバレッジの手法](../../docs/method/code-coverage.md)を参照してください。

## 回路と期待値

回路は`req_valid && req_ready`で演算種別・2オペランド・enable・authorizedを受け取ります。enableとauthorizedがともに1なら、幅8／16ビットの剰余加算またはXORを実行し、それ以外はデータ0・error=1を返します。IDLEからEXECまたはDENYを経てRESPへ進み、応答を受理されるまで保持します。要求受理から2クロック後に応答が有効になります。同期・Low有効のリセットは保留処理を取り消します。

Pythonは受理時の要求から期待結果と応答期間を求め、C++ハーネスは実際のRTLのready・valid・データ・errorを比較します。演算中の入力変更、応答待ち、リセットでの取消しも照合します。カバレッジが増えたことだけで機能比較を省略しません。

## 実行

Python 3.10以上、Verilator 5.052、C++20コンパイラーとmakeを用意し、リポジトリのルートで実行します。`verilator_coverage`も同じVerilatorの配布物を使います。

```sh
python3 examples/local-code-coverage/run.py --out artifacts/code-coverage-demo
python3 examples/local-code-coverage/run.py --profile nightly --out artifacts/code-coverage-nightly
python3 -m unittest discover -s examples/local-code-coverage/tests -v
```

`--configuration width8|width16|all`、`--seed`、`--verilator`、`--coverage-tool`、`--jobs`、`--timeout`、`--build-timeout`、`--out`を指定できます。既存の出力先は上書きしません。smokeの追加試験は固定ケース＋ランダム8操作、nightlyは固定ケース＋100操作を3 seedで実行します。固定ケースだけでも必須ポイントに到達します。

## 基礎試験・追加試験・統合

基礎試験は小さな値の加算だけを実行します。機能比較は通りますが、XOR、拒否応答、待ち、データの上位ビット等が未達になります。追加試験で両演算・桁あふれ・全ビットの変化・3種類の許可不足・応答保持・途中リセットを確認します。

[coverage-plan.json](coverage-plan.json)で、各構成のポイント集合のハッシュ、指標別の個数、必須から分ける2項目と理由を固定しています。RTLのハッシュ、DBのソース・種類・重複・集合を確認し、項目欠落や版違いを拒否します。異なる幅の率やDBで不足を補いません。

8ビット構成の確認結果（Verilator 5.052）は次のとおりです。物理的なソース行数ではなく、ツールが生成したポイントを数えています。

| 指標 | 基礎試験の達成／生成数 | 統合後の達成／生成数 | 必須判定の達成／必要数 |
| --- | --- | --- | --- |
| 行・基本ブロック | 5/7 | 6/7 | 6/6 |
| 分岐 | 14/18 | 18/18 | 18/18 |
| 式 | 13/16 | 16/16 | 16/16 |
| toggle | 67/108 | 108/108 | 108/108 |
| FSM状態 | 3/4 | 4/4 | 4/4 |
| 抽出されたFSM遷移 | 3/6 | 5/6 | 5/5 |

注釈レポートの`Annotation Summary`は、各行に付随する全ポイントの達成状況を集計するため、上表の`line`指標の率とも区別します。

16ビット構成ではtoggleの生成数は188、基礎試験は99/188、統合後は188/188です。その他の個数は同じです。lineとFSM遷移の原本には、未達のdefault項目が各1個残ります。2ビットの全4符号をcaseで列挙しており、2値モデルで通常到達しない防御用のdefaultと、ツールが作るdefault遷移です。これらを必須から分ける根拠と、除外前の分母・ゼロの記録を残します。

Verilator 5.052のFSM抽出には制約があります。本回路では状態4個と遷移6項目が生成されますが、IDLEからの条件分岐と自己遷移はFSM項目に含まれていません。分岐・式と機能比較で確認し、上表をソース全体のFSM遷移網羅率とは扱いません。Low有効リセットを内部の正論理信号へ対応させた状態専用の`always_ff`と、FSMメタコメントを使って計測を確認しました。

## 合格条件と対照確認

同じ構成・同じ計測設定の、機能比較と全サイクルの完了検査が成功したDBだけを、実際の`verilator_coverage --write`で統合します。統合後の全カウンターが入力DBの和と一致すること、指標ごとの必須項目がヒットしていることを確認します。全体の平均率だけでは判定しません。

次の対照確認も行います。

- **刺激不足**：基礎試験に必須ポイントの未達が残ることを確認します。この試験の正しい実測値は、後の統合へ利用します。
- **演算結果の誤り**：演算結果の下位1ビットを壊した回路を全ケースで動かします。必須カバレッジが達成されても、完全な操作列の機能比較は`CODE_DATA`で失敗する必要があります。このDBは統合へ加えません。
- **計測なし**：カバレッジを有効にせずビルドした回路が機能比較に合格しても、DB欠落として判定から拒否します。ビルド失敗やクラッシュをこの診断の成功へ数えません。

起動前の初期化を終えてからカウンターをクリアし、その後の入力列に含むリセットは計測します。式の項目はVerilatorの定義に従い、MC/DCの証跡には使いません。

## 証跡と確認結果

出力先にはマニフェスト・ツール版・ビルドログ、ケース別のベクトル・実行ログ・波形・`coverage.dat`・`result.json`、統合DB、指標別の全ポイント・ゼロ項目・必須から分けた根拠、`summary.json`、`junit.xml`を保存します。終了時にソースハッシュの一致も確認します。

`width8-coverage.json`と`width8-annotated/command_unit.sv`で、統合結果とソースの注釈を確認できます。基礎試験の注釈を別途作る場合は、次のように実行します。

```sh
verilator_coverage --annotate artifacts/code-coverage-demo/baseline-annotated \
  --annotate-all --annotate-points --annotate-min 1 \
  artifacts/code-coverage-demo/width8-baseline/coverage.dat
```

JUnitはsmoke 23件／nightly 27件です。セルフテスト10件には、DBの欠落・重複・不正値・別ソース、統合時の集合不一致、空の必須集合、ソース変更、カバレッジ達成時の機能失敗、実ツールでの統合と注釈生成を含みます。2026-10-31に両構成のsmoke／nightly・10セルフテスト、全構成・変異0／1のVerilator lintとYosysの構造検査が成功しました。

[Verilatorの計測定義](https://verilator.org/guide/latest/simulating.html#coverage-analysis)、[オプション](https://verilator.org/guide/latest/exe_verilator.html#cmdoption-coverage-line)、[DB統合と注釈](https://verilator.org/guide/latest/exe_verilator_coverage.html)を参照しています。この例は新規作成の2値モデルで、全SystemVerilog構文・全FSMの抽出・4値やX伝搬・MC/DC・商用DBとの互換性の確認は含みません。
