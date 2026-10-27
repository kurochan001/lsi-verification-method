# AHB-Lite／AXI4-Liteをローカルでフォーマル検証する

[AHB-Lite](../local-ahb/README.md)と[AXI4-Lite](../local-axi/README.md)の実行例に対し、安全性の証明、データの有界検査、到達性、変異検出を追加する教材です。GitLabや商用EDAライセンスを使わず、Yosys・SymbiYosys（SBY）・Z3で実行します。ランダムシミュレーションとは別の検証計画・証跡として扱います。

## 1. 準備と実行

POSIX環境とPython 3.10以上を使います。確認済みパッケージを[requirements](tools-requirements.txt)から一時仮想環境へ導入します。既存FIFO例と同じ固定版のYoWASP・Z3を利用し、システム全体へインストールしません。

```sh
python3 -m venv /tmp/lsi-bus-formal-venv
. /tmp/lsi-bus-formal-venv/bin/activate
python3 -m pip install -r examples/local-bus-formal/tools-requirements.txt
python3 examples/local-bus-formal/run.py --out artifacts/bus-formal-all
```

リポジトリのルートから実行してください。既存の仮想環境を再利用する場合は、上書きせず、その環境をactivateしてパッケージ版を確認します。[YoWASP](https://yowasp.org/)はWebAssembly版の非公式配布です。パッケージ・ツール・Pythonの実際の版を保存します。

```sh
python3 examples/local-bus-formal/run.py --bus ahb --configuration ahb-wait3 --out artifacts/formal-ahb-wait3
python3 examples/local-bus-formal/run.py --bus axi --configuration axi-delay2 --out artifacts/formal-axi-delay2
python3 -m unittest discover -s examples/local-bus-formal/tests -v
```

既定は全5構成です。AHBは`ahb-wait0`／`ahb-wait1`／`ahb-wait3`、AXIは`axi-delay0`／`axi-delay2`を選べます。確認テスト12件はフォーマルツールなしでも実行でき、実際の証明を実行するコマンドとは別です。

## 2. タスクと保証範囲

各構成で次の9タスクを実行し、全5構成でJUnit **45件**を出力します。

| タスク | 必要な結果 | 結果の意味 |
| --- | --- | --- |
| safety-proof | proveのPASSと帰納法完了 | 下記の安全性プロパティを仮定の下で非有界に証明 |
| data-bmc | bmcのPASS、既定深さ12 | データ・応答比較を含む対象プロパティに、その深さまで反例なし |
| scenario-cover | 全目標の到達とwitness | AHB 8／AXI 12目標へ至る経路を取得 |
| detect-mutation1〜4 | 予定したassertのFAILと反例 | 既存4変異を検出する検証環境の感度確認 |
| overconstrained-proof | proveのPASS | 診断として常時リセットを仮定した場合の結果 |
| detect-overconstraint | 全正常目標が深さ12で未到達 | 上記の過剰な仮定で正常動作を確認できないことを検出 |

`--bound 12`がBMCとcoverの既定です。12〜100の範囲で変更できます。深くするほど実行時間・メモリが増えます。proveの12は帰納法の探索上限であり、PASSと帰納法完了が得られれば、保証を12サイクルだけに限定する値ではありません。

`--timeout`は各ツール取得・各SBYタスクに対する秒数で、既定120秒です。内部のSBY制限を少し短くし、外側でもプロセスグループを停止します。TIMEOUTやUNKNOWNは成功へ変換しません。既存の`--out`は上書きしません。

## 3. 何を証明・比較するか

### AHB-Lite

通常のproveでは、応答タイミング、リセット時応答、ERRORの前半から後半への遷移の**3プロパティ**を証明します。BMCではデータ比較`ap_data`を加え、計4プロパティを検査します。

ハーネスは、受付済みのアドレス・サイズ・方向と経過時間を記録し、予定のready・ERROR応答を比較します。データフェーズでは現在のHADDRへ追従せず、受付済みの要求とHWDATAを対応付けます。

8つのcoverは、正常書込み、正常読出し、パイプライン、ERROR前半、ERROR完了、狭いサイズの書込み、転送中リセット、その後の読出し復帰です。HTRANSやHBURSTの全バースト規則を証明するハーネスではなく、既存回路の受付・応答の契約を検査します。不正アドレスや過大HSIZEも禁止せず、教材のエラー方針を確認します。

### AXI4-Lite

通常のproveでは、READY、VALID生成時期、B／R応答の保持、応答と先行要求の因果関係、リセットの6プロパティに、帰納法の補助不変条件5個を加えた**11プロパティ**を証明します。BMCではデータ・応答内容の比較`ap_payload`を加え、計12プロパティを検査します。

補助条件は、DUTの読出し処理とRVALIDの排他、待ちカウンタの範囲、書込み処理・BVALID・受付スロットの整合、参照モデルの経過時間の範囲と待機状態の整合です。DUT側の4条件は、RTLの`FORMAL`定義時だけ有効なassertとして追加しています。**assumeで成立させる条件ではなく、これらも証明対象**です。通常シミュレーション時の回路動作は変えません。

12のcoverは、AW先行、W先行、同時、B待ち、R待ち、WSTRB=0、読書きの並行、エラー応答、片側要求でのリセット、応答保留中のリセット、復帰、Rを待たせた同一アドレスへの書込みです。

AXI4-Liteには複数未完了転送を扱える実装もありますが、この回路は各方向1件へ受付を制限します。AXI4の複数ビート、IDやアウトオブオーダーの検証例ではありません。

### データを追跡する方法

任意の定数`watched_index`で4個のレジスタのうち1ワードを選び、参照値を保持します。選択したワードへの書込みだけを仕様のレーンで反映し、そのワードの読出しと比較します。IDとエラー応答も比較します。

選択値を特定の番号へ制約していないため、ソルバーは誤りのある任意のワードを選んで反例を探せます。特定の1番地だけを確認した結果ではありません。データ値の比較はBMCに限り、非有界のデータ整合性証明と混同しません。AXIの読出し値はAR受理時に保存し、同じエッジの書込みより前の値とします。この優先順位は教材独自のレジスタ仕様です。

## 4. 入力の仮定とモデルの限界

正常タスクの入力仮定は次のものだけです。コンパイル後にも固定した名前・件数と照合します。

- 共通：最初のサンプリングエッジではリセット。
- AHB：通常の待ち中に提示した有効な次アドレス・制御を保持。書込みデータも待ち中は保持。ERROR後の次要求取消しは禁止しない。
- AXI：AW／W／ARのVALIDを上げてREADYを待つ間、VALIDと内容を保持。

初回以降のリセット、AW／Wの到着順、アドレス、データ、WSTRB、BREADY／RREADYは任意です。受信側のREADYがいつか上がるという公平性の仮定は置きません。そのため、応答保持の安全性を確認できても、無期限にREADY=0の相手との最終的な転送完了を保証するものではありません。

単一クロック・2値モデルで、`async2sync`により非同期リセットをサンプリングエッジで観測するモデルへ変換します。エッジ間のリセットパルス、recovery／removal、X/Z、CDC、実装後タイミングは対象外です。即時のassert／assume／coverを使い、SVA全構文のサポートを示す例ではありません。[SBYのVerilog拡張](https://yosyshq.readthedocs.io/projects/sby/en/stable/verilog.html)

## 5. 変異と過剰な仮定の診断

| 変異 | AHBで必要な反例 | AXIで必要な反例 |
| --- | --- | --- |
| 1 | ap_data：アドレスとデータの誤対応 | ap_payload：受理後のWDATAへ依存 |
| 2 | ap_data：レーン無視 | ap_payload：WSTRB無視 |
| 3 | ap_response：1サイクルERROR | ap_valid：待ち中のBVALID消失 |
| 4 | ap_data：読出しLSB反転 | ap_payload：保留RDATAの変化 |

常時リセットという追加のassumeは、診断2タスクだけに入れます。証明がPASSしても、通常の全到達目標は未達になります。この未達は有限深さの結果で、任意の未到達に対して一般的な到達不能を証明したとは報告しません。ここでは実際の仮定も確認して原因を特定します。

```sh
python3 examples/local-bus-formal/run.py --bus ahb --configuration ahb-wait0 --demo-bug 1 --out artifacts/formal-intentional-failure
```

これは通常モデル側にも変異1を入れ、回帰の終了コード1を期待するデモです。AHBでは安全性証明がPASSしてもデータBMCがFAILすることを確認できます。通常のcoverと変異検出ケースは、それぞれ元回路・専用変異のまま実行します。

## 6. 判定と証跡

出力先に、全タスク・仮定名・プロパティ名・構成・探索深さ・パッケージ版・入力ハッシュの`manifest.json`、版取得の`tools.json`とログ、構成別`coverage.json`、結果の`summary.json`、`junit.xml`を保存します。タスク別には、RTL・ハーネスの写し、生成SBY設定、コンパイル済みモデル、全ログ、status、反例／到達のVCDとwitness、個別`result.json`を残します。

`inventory.json`から、実際に構成されたパラメーター、assert／assume／coverを固定計画と照合し、欠落・追加・同名重複を拒否します。proveは帰納法完了、BMCはエンジン完了、coverは全目標とトレース、変異は予定assertの違反とVCD・witnessを要求します。無関係なクラッシュ、別のassertだけの違反、証跡の欠落を検出成功にはしません。

通常モデルのcoverだけを構成別に集計し、診断や変異の観測は加算しません。フォーマルのAHB 8／AXI 12目標と、シミュレーションのAHB 21／AXI 39目標は別計画です。フォーマルの到達でシミュレーション側の未達を埋めません。[SBYの設定資料](https://yosyshq.readthedocs.io/projects/sby/en/stable/reference.html)

## 7. 実行確認

2026-10-27に、固定版のYoWASP・Z3とPython 3.14.7を使い、AHB 3構成27タスクとAXI 2構成18タスク、計45タスクが予定どおりの結果になりました。正常の48到達目標、20変異の反例、5構成の過剰な仮定の診断を確認しました。AHBのdemo-bug 1では、安全性証明がPASS、データBMCがFAILとなり、回帰が終了コード1になりました。判定・証跡の確認テスト12件も成功しました。

ランダム検証も拡張し、AHBのバースト・BUSY・動作中リセット、AXIの長い応答待ちとAWのみ／Wのみ／B保留／R保留でのリセットを追加しました。全5構成のsmoke／nightlyが成功しています。GitLabへの登録・CI起動や既存CI設定の変更は行っていません。
