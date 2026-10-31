[![License: Apache-2.0 WITH LLVM-exception](https://img.shields.io/badge/License-Apache--2.0%20WITH%20LLVM--exception-blue)](LICENSE)
[![RTL: SystemVerilog](https://img.shields.io/badge/RTL-SystemVerilog-8A2BE2)](examples/README.md)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](#準備と実行)
[![Verification: SVA / UVM / Formal](https://img.shields.io/badge/Verification-SVA%20%2F%20UVM%20%2F%20Formal-2e7d32)](#検証の進め方)

# LSI検証手法

LSIの仕様から検証を計画し、刺激・観測・期待値の比較・カバレッジ・証跡を対応付けて、検証の完了を判断するためのリポジトリです。検証手順書、ローカルで動くRTLと検証環境、記録の雛形、手法の適用事例を収録しています。

例えば、FIFOなら「空や満杯で同時に読書きを要求したらどうなるか」、割り込み回路なら「イベントとクリアが重なったらどちらを優先するか」を仕様から読み取り、入力・期待結果・確認条件へ落とし込みます。実行例では、正常な動作の確認に加え、意図的な誤実装を検出できるか、必要な条件を試せているかも確認します。

<a id="読む順序"></a>

## 目的から資料を選ぶ

| 目的 | 入口 |
| --- | --- |
| 検証の全体的な進め方を知る | [検証手法の案内](#検証の進め方)／[一般化した手順書](docs/method/spec-to-verification-method.md) |
| 対象の回路や検証方式に合う例を探す | [分野別の案内](#検証例一覧)／[全検証例の一覧](examples/README.md) |
| 手元で実行する | [準備と実行](#準備と実行) |
| 計画と結果を記録する | [適用範囲](docs/templates/verification-scope.md)／[サインオフ記録](docs/templates/signoff-record.md) |
| 用語や結果の読み方を確認する | [用語集](docs/glossary.md)／[FAQ](docs/faq.md) |
| 適用事例と由来を調べる | [IEEE 1800-2023のケーススタディ](docs/case-study-ieee1800/README.md)／[PROVENANCE.md](PROVENANCE.md) |

資料は、**手法を読む → 小さな回路で試す → 計画と結果を記録する**、という順で使えます。実際の仕様へ適用するときは、例の要求や合格条件を、対象IPの仕様・構成に合わせて見直します。

```mermaid
flowchart LR
  accTitle: 手法・実行例・記録のつながり
  accDescr: 手法文書で検証の考え方を学び、実行例で刺激と判定を試し、テンプレートへ計画と結果を記録する。ケーススタディは具体的な適用と見直しの参考になる。
  M["手法を読む<br/>docs/method"] --> E["RTLと検証環境を動かす<br/>examples"]
  E --> T["計画・結果を記録<br/>docs/templates"]
  C["ケーススタディを参照<br/>手法を適用した記録"] -.-> E
```

## 検証の進め方

### 全体像

```mermaid
flowchart TD
  accTitle: 仕様から検証の完了判断まで
  accDescr: 要求と合格基準を定め、刺激と判定をレビューし、実行証跡と未達を確認して見直す流れ。
  R["仕様・要求ID・観測点・合格基準"] --> P["刺激・チェッカー・到達目標を独立レビュー"]
  P --> E["実行し、入力の版・結果・未達を保存"]
  E --> J["必須範囲と残リスクから完了判断"]
  J -- "追加検証" --> P
  J -- "仕様の見直し" --> R
```

仕様を、条件と期待結果を確認できる要求へ分け、要求ごとに刺激・観測点・判定を用意します。作成者とは別の担当者が仕様との整合性と検出力をレビューし、対象の版と構成に対応する証跡を残します。

### 検証環境で何を確認するか

検証対象のRTLを**DUT（Design Under Test）**、入力を与えて結果を調べる側を**テストベンチ**と呼びます。下図はシミュレーション環境の概念図です。仕様と入力から期待結果を求め、RTLの実装とは独立した基準で実際の動作と比較します。各例が備えるチェッカーや計測方式は、それぞれのREADMEに示しています。

```mermaid
flowchart TD
  accTitle: シミュレーションの刺激・観測・判定・カバレッジ
  accDescr: 同じ入力をRTLと参照モデルへ与え、RTLの観測結果と独立した期待値を比較する。アサーションは信号の関係を検査し、機能カバレッジとコードカバレッジは到達状況を計測する。
  S["刺激生成<br/>固定ケース・ランダム入力"] --> D["検証対象のRTL<br/>DUT"]
  S --> R["参照モデル<br/>期待結果を求める"]
  D --> M["モニター<br/>入出力・受理・完了を観測"]
  R --> B["スコアボード<br/>期待結果と比較"]
  M --> B
  D --> A["アサーション<br/>値・時間関係を検査"]
  M --> F["機能カバレッジ<br/>仕様から選んだ条件を計測"]
  D -. "実行状況を計測" .-> C["コードカバレッジ<br/>行・分岐・信号変化など"]
```

例えば、データの値と順序はスコアボード、待ち中の信号保持はアサーション、空・満杯・同時要求の組合せは機能カバレッジで確認できます。それぞれが答える問いを分けると、結果を読み違えにくくなります。

| 手段 | 確認すること | 結果を読むときの注意 |
| --- | --- | --- |
| 期待値比較・アサーション | 実行した動作の値・順序・時間関係が要求どおりか | 違反が0でも、必要な条件を試したとは限らない |
| 機能カバレッジ・cover | 仕様から選んだ機能・状態・境界・組合せに到達したか | 到達率100%でも、出力が正しいとは限らない |
| コードカバレッジ | RTLの行・分岐・式・信号変化・状態遷移をどこまで実行したか | 実装の欠落や、仕様に対する検証項目の抜けは別に点検する |
| フォーマル検証 | 仮定とモデルの範囲で、プロパティが成立するか | 証明対象・仮定・到達性、有界検査と証明の違いを確認する |

**検証の完了判断**では、これらの結果を要求へ対応付け、必須構成・証跡・未達・例外・残リスクをレビューします。到達率や失敗件数だけで、製品の検証完了とは判断しません。

### 計画と対象範囲を決める

| 資料 | 主な内容 |
| --- | --- |
| [仕様から検証へ](docs/method/spec-to-verification-method.md) | 要求の抽出、検証方式の選定、独立レビュー、完了条件 |
| [検証領域の抜けを点検する](docs/method/verification-gap-review.md) | lint、リセット・X、CDC/RDC、性能、低電力、保護、統合、物理・製造 |
| [機能間の相互作用とクロス検証](docs/method/feature-interaction-verification.md) | 同時動作・順序・中断と復帰、因子・制約・重点目標。[提案](docs/feature-interaction-coverage-proposal.md)／[記録](docs/templates/interaction-coverage-plan.md)も収録 |
| [検証規模を削減する](docs/method/verification-reduction.md) | 境界・代表構成・組合せ・テストの削減、目標と検出力を維持する根拠 |

例えば[割り込み回路のSVA例](examples/local-sva/README.md)では、「イベントを保持し、W1Cでクリアし、許可中だけIRQを出す」という仕様を、次のように分けます。W1C（Write One to Clear）は、1を書いたビットをクリアする方式です。

| 要求 | 起こす条件 | 判定と到達の確認 |
| --- | --- | --- |
| 同時イベントとクリアではセットを優先する | 同じクロックでイベントとクリアを受理 | 保持状態が1になることをassertし、前件と結果のcoverも確認 |
| 操作がなければ状態を保持する | イベントもクリアもない期間を作る | 保持状態が変わらないことをassertし、保持条件をcover |
| 許可に関係なくイベントを保持する | マスク中にイベントを受理し、後で許可する | マスク中のセットとIRQの論理関係をassertし、マスク中／許可中をcover |

この例では、受理したエッジで状態を更新し、状態更新のSVAは次のクロックのサンプルで結果を確認します。クロック・リセット・観測時点まで要求と合わせることが、再現できる判定につながります。

### 刺激・チェッカー・証明を用意する

| 資料 | 主な内容 |
| --- | --- |
| [制約付きランダム検証](docs/method/constrained-random-verification.md) | 合法な刺激、分布、seed、再現、未達への調整、失敗の縮小 |
| [SVAのアサーションとカバー](docs/method/sva-verification.md) | assert・assume・cover、サンプリング、履歴、リセット、終了時の扱い |
| <a id="目視確認をアサーションに置き換える"></a>[目視確認から自動判定へ](docs/method/assertion-based-regression.md) | 目視条件を明文化し、検出力を確認してリグレッションへ組み込む。[移行記録](docs/templates/assertion-migration.md)も用意 |
| [UVMへの適用](docs/method/uvm-verification.md) | agent・monitor・スコアボード、RAL、要求との対応、合格条件 |
| [フォーマル検証](docs/method/formal-verification.md) | 仮定・初期状態、抽象化・分割、有界検査と証明、反例・到達性 |

目視で確認していた条件は、「どの入力を、いつ受理したら、何が起こるか」へ分けてアサーションにします。正常時に通ること、既知の誤動作で失敗すること、前件への未到達やチェッカー無効化を見逃さないことを確認し、終了コードと証跡を伴うリグレッションへ残します。波形は、失敗原因の解析や観測条件の検討に使えます。

### 網羅性・検出力・継続実行を管理する

| 資料 | 主な内容 |
| --- | --- |
| <a id="機能カバレッジを確認する"></a>[機能カバレッジ](docs/method/functional-coverage.md) | 仕様から機能・状態・境界・crossを選び、必須binの到達と比較結果を対応付ける |
| <a id="コードカバレッジを確認する"></a>[コードカバレッジ](docs/method/code-coverage.md) | 行・分岐・式・toggle・FSMの計測、未達分析、追加試験、DB統合と除外 |
| [ミューテーション検証](docs/method/mutation-verification.md) | 意図的な誤りで検出力を確認し、未検出・等価な変異・未完了を区別する |
| [継続的リグレッション](docs/method/continuous-regression.md) | 変更時・定期・サインオフの計画、予定と結果の照合、資源・再実行・証跡管理 |

機能カバレッジの例では、パケットスイッチの「出力ポート×末尾の有無×受信側ready」をcrossで計測し、どの組合せを試したかを確認します。コードカバレッジの例では、基礎試験で残ったXORや拒否応答などの未達を、追加試験とDB統合で補います。未達の原因を調べ、刺激不足、到達不能、計測の問題、要求・実装の不足を分けて扱います。

## 検証例一覧

分野を選ぶと、対象範囲・主な検証内容・必要なツールを記載した一覧へ進めます。個別の実行手順と合格条件は、各例のREADMEを参照してください。

### 学びたいことから選ぶ

最初はFIFOで「刺激を与える・期待値と比べる・必要な条件を確認する・不具合を検出する」を一通り試せます。その後は、目的に合う例へ進んでください。

| 学びたいこと | 入口となる資料・例 | 見るポイント |
| --- | --- | --- |
| RTLの入出力を自動で比較する | [同期FIFO](examples/local-fifo/README.md) | 独立した参照キュー、空／満杯、データ順序、変異検出 |
| 周辺回路を結合して確認する | [APB・UART・割り込み](examples/local-apb-uart/README.md) | バス操作から送受信・IRQまでのつながり、待ち・リセット |
| 波形の目視確認を自動判定にする | [割り込みのSVA](examples/local-sva/README.md) | assertとcover、サンプリング、検出力、終了判定 |
| 仕様から選んだ条件を計測する | [ネイティブ機能カバレッジ](examples/local-functional-coverage/README.md) | DRAM・SHA-256・スイッチのbin・cross、ヒット数と未達 |
| RTLの未実行箇所を調べる | [コードカバレッジ](examples/local-code-coverage/README.md) | 基礎試験と追加試験、DB統合、注釈付きソース |
| 入力空間の広い回路を証明する | [RISC-V命令デコーダ](examples/local-riscv-decoder/README.md) | 全命令語の合法性判定、合法命令の出力、誤実装の反例 |
| AIを使った検証を学ぶ | [AIの使い方](docs/method/spec-to-verification-method.md#12-並列化とaiの使い方)／[適用事例](docs/case-study-ieee1800/README.md) | 要求抽出・テスト案作成、作成とレビューの分担、実行証跡による確認 |

AIは、要求の整理、テスト・アサーション案の作成、未達や失敗の分析を支援するために使います。提案は仕様と照合し、独立レビューと実際の実行結果で、妥当性と不具合の検出力を確認します。

### 分野から選ぶ

| 分野 | 主な題材 |
| --- | --- |
| <a id="バスレジスタアドレス"></a>[バス・レジスタ・アドレス](examples/README.md#バスレジスタアドレス) | APB・AHB・AXI、幅変換、アドレスマップ |
| <a id="fifo通信仲裁"></a>[FIFO・通信・仲裁](examples/README.md#fifo通信仲裁) | FIFO、ready/valid、UART・SPI・I²C、再送・パケットスイッチ |
| <a id="割り込みタイマー周辺機能の結合"></a>[割り込み・タイマー・周辺機能の結合](examples/README.md#割り込みタイマー周辺機能の結合) | 割り込み、タイマー、ウォッチドッグ、周辺回路の接続 |
| <a id="dmaメモリ順序制御"></a>[DMA・メモリ・順序制御](examples/README.md#dmaメモリ順序制御) | DMA、DRAM、キャッシュ、コヒーレンシ、可視性と順序 |
| <a id="cdcクロックリセット低電力"></a>[CDC・クロック・リセット・低電力](examples/README.md#cdcクロックリセット低電力) | 非同期転送、クロック停止、リセット、隔離・保持・復帰 |
| <a id="演算故障注入保護性能dft"></a>[演算・故障注入・保護・性能・DFT](examples/README.md#演算故障注入保護性能dft) | DSP、SHA-256、ECC、アクセス保護、MBIST、JTAG・スキャン |
| <a id="ai用回路"></a>[AI用回路](examples/README.md#ai用回路) | シストリックアレイ、再量子化、活性化、畳み込み、Top-K、GEMM |
| <a id="プロセッサ"></a>[プロセッサ](examples/README.md#プロセッサ) | RISC-V、ISS比較、デコーダ、PMP・Sv32・TLB、除算器 |
| <a id="静的タイミング解析"></a>[静的タイミング解析](examples/README.md#静的タイミング解析) | OpenSTA、setup／hold、制約の欠落・経路消失 |
| <a id="フォーマル検証等価性反例再現"></a>[フォーマル検証・等価性・反例再現](examples/README.md#フォーマル検証等価性反例再現) | 証明、到達性、等価性、反例再現、接続性 |
| <a id="svauvm仕様生成ソフトウェア連携検証効率"></a>[SVA・UVM・仕様生成・ソフトウェア連携・検証効率](examples/README.md#svauvm仕様生成ソフトウェア連携検証効率) | アサーション、機能／コードカバレッジ、UVM・RAL、生成、C・cocotb、探索・削減 |

全例の詳細は[検証例一覧](examples/README.md)、構成・実行数・過去の確認結果は[集計と実行記録](examples/README.md#集計と実行記録)にまとめています。

2026-10-31に、nightly対応全83例の記載構成、集約7本、全10フォーマル例の既定全タスクを再実行しました。[全例の実行確認](PROVENANCE.md#全例のnightlyと全フォーマル例の再実行2026-10-31)に範囲と結果を記録しています。

## 準備と実行

リポジトリ全体を取得し、ルートディレクトリから実行します。例同士でRTLや共通ランナーを再利用しています。

### 最初のシミュレーション

POSIX環境（macOS／Linux）、Python 3.10以上、Icarus Verilog（`iverilog`・`vvp`）を用意します。最初は、期待値比較とランダム入力を扱う同期FIFOの例から試せます。

```sh
python3 examples/local-fifo/run.py
```

既定では**深さ3・データ幅8の1構成**をsmokeで実行します。境界テスト、ランダム入力、3種類の誤実装の検出、必須目標の判定をまとめて行います。正常に完了したときの代表的な出力は次のとおりです（抜粋）。

```text
PASS     d3-w8-boundaries: 85 checked cycles
DETECTED d3-w8-detect-mutation1: expected mutation detected by FIFO_DATA_ORDER
Coverage: 22/22 required goals
Regression: PASS
```

`DETECTED`は、意図的に入れた誤実装を予定したチェッカーで検出できたことを示します。通常回路の失敗とは別に判定します。`22/22`はこの構成の必須目標の達成数であり、FIFOの全入力・全操作列を網羅したという意味ではありません。

構成を明示し、長めのランダム検証を行う場合は次のように実行します。

```sh
python3 examples/local-fifo/run.py --depth 3 --width 8 --profile nightly --seed 73
```

| プロファイル | 通常回路の刺激 | 共通して判定すること |
| --- | --- | --- |
| smoke | 境界テスト＋1 seed・200ランダムサイクル | 期待値比較、3種類の変異検出、構成別の必須目標 |
| nightly | 境界テスト＋3 seed・各2,000ランダムサイクル | 同じ合格条件で、より長い操作列を確認 |

`nightly`は実行量を選ぶ名前で、自動スケジュールを設定するものではありません。seedは再現の手掛かりとして、実際の入力列・ソース・ツール版と一緒に保存します。

同じ環境で、[AHB-Lite](examples/local-ahb/README.md)や[AXI4-Lite](examples/local-axi/README.md)なども実行できます。オプション、カバレッジ・JUnit・証跡の形式は[Icarus共通手順](examples/local-common/README.md)を参照してください。

### アサーションとカバレッジを実測する

Verilator 5.052、C++20コンパイラー、makeを使う例です。コードカバレッジには、同じ配布物の`verilator_coverage`も使います。

| 実行例 | コマンドと確認内容 |
| --- | --- |
| [SVAによる自動判定](examples/local-sva/README.md) | `python3 examples/local-sva/run.py` — 正常動作、誤実装検出、前件・完了経路、無効化の拒否 |
| [ネイティブ機能カバレッジ](examples/local-functional-coverage/README.md) | `python3 examples/local-functional-coverage/run.py` — DRAM・SHA-256・スイッチのcoverpoint・crossとbin別件数 |
| [コードカバレッジの未達分析](examples/local-code-coverage/README.md) | `python3 examples/local-code-coverage/run.py` — 追加試験、DB統合、注釈付きソース、計測漏れと機能不正の検出 |

各例は`--profile nightly`で試験を拡張できます。機能カバレッジとコードカバレッジは対象と分母が異なり、到達した動作の正しさは期待値比較と併せて確認します。

多くのIcarus例は、テストベンチの`COVER`ログを要求カタログと照合します。上記の機能カバレッジ例は`covergroup`・`coverpoint`・`cross`を、SVA例は`cover property`を使って、ネイティブの`coverage.dat`も照合します。計測方式と必須項目を確認し、異なる分母の率を一つの達成率へ混ぜないようにします。

### 結果と証跡を読む

ランナーは、比較結果に加えて、予定ケースの完了と必要な目標への到達を確認します。正常終了した通常ケースと、誤実装・計測不足を意図的に起こした診断ケースは分けて記録します。無関係なクラッシュやタイムアウトを、不具合の検出成功とは数えません。

FIFO例は既定で`artifacts/fifo-local-日時/`へ結果を保存します。主なファイルは次のとおりです。ほかの例でも同様の情報を保存しますが、詳細なファイル名・構成は各READMEを参照してください。

| 証跡 | 調べること |
| --- | --- |
| `summary.json` | 全体の合否、予定／完了ケース数、通常実行と変異検出の結果 |
| `coverage.json` | 構成ごとの必須目標・達成・未達と、それを観測したケース |
| `manifest.json` | 実行したソースのハッシュ、構成、seed、入力列などの再現条件 |
| `junit.xml` | ケース別の結果を、対応する結果表示ツールやCIへ取り込む |
| ケース別ログ・入力列・VCD波形 | 失敗ラベルから、入力・観測値・時刻を追って原因を調べる |

失敗時は、まず全体の完了状況と失敗ラベルを確認し、該当ケースのログ・波形・未達目標を調べます。仕様と期待値の根拠を確認して修正し、再現ケースと関連する構成を再実行します。既知の不具合は、変更後も自動判定できる固定ケースやアサーションへ残します。

`--out`で出力先を指定する場合は、新しいディレクトリを選びます。既存の証跡は上書きしません。合否の基準と出力形式の詳細は、[FIFO例](examples/local-fifo/README.md)と[Icarus共通手順](examples/local-common/README.md)を参照してください。

### 専用環境を使う例

| 対象 | 準備・共通手順 |
| --- | --- |
| フォーマル検証 | [Yosys・SBY・Z3の固定版環境](examples/local-formal-common/README.md) |
| UVM・RAL・制約付きランダム化 | [UVMの準備](examples/local-uvm/README.md)／[UVMランダム化の準備](examples/local-uvm-random/README.md) |
| SystemRDL・cocotb・C連携 | [仕様生成](examples/local-register-spec/README.md)／[cocotb](examples/local-cocotb/README.md)／[ホスト連携の共通処理](examples/local-host-common/README.md) |
| 探索・縮小・UVMの証跡管理 | [固定計画と実行記録の共通処理](examples/local-exploration-common/README.md) |

上記以外の追加ツール・版・セットアップも、各例のREADMEで確認してください。

### まとめて実行する手順

関連する例を親ランナーから起動できます。個別の検証例と重複するため、検証例の数やJUnit件数を集計する際は、同じ結果を二重に数えないようにします。必要なツールと、実行範囲を選ぶオプション（`--stage`）の指定はリンク先を参照してください。

| 集約手順 | 含まれる検証例 |
| --- | --- |
| [システム検証の7例](examples/local-system-regression/README.md) | DMA、複数マスター、非同期APB、復旧、低電力、AXI4フォーマル、FIFO等価性 |
| [ソフトウェア・差分・完了期限の7例](examples/local-advanced-regression/README.md) | AXI4-Stream、Cドライバ、メモリ競合、DSP、cocotb、差分検証、完了期限 |
| [解析・収束・結合・UVMの7例](examples/local-workflow-regression/README.md) | 幅変換、アクセス保護、ECCメモリ、クロック・リセット、操作列縮小、刺激調整、UVM |
| [UVMランダム化・仕様生成・反例再現の7例](examples/local-soc-regression/README.md) | UVMランダム、SystemRDL、反例再現、優先順位付きIRQ、リングDMA、クレジット通信、キャッシュ |
| [RAL接続・順序制御・DMAなどの7例](examples/local-extension-regression/README.md) | 生成RAL、AXI応答順序、DMA所有権、Stream DMA、CRC、カウンター、MBIST |
| [セキュリティ・性能・CDCなどの6例](examples/local-gap-regression/README.md) | セキュリティ、性能モニター、CDCハンドシェイク、JTAG、アドレスマップ、ロックステップ |
| [AI用回路の6例](examples/local-ai-regression/README.md) | シストリックアレイ、再量子化、活性化関数、ラインバッファ、Top-K、FP16／MXFP8／MXFP4 |

## このリポジトリについて

### 構成

```text
docs/method/                    検証手法の説明
docs/glossary.md・docs/faq.md    用語と、方式・結果の読み方
docs/templates/                 計画・移行・結果・サインオフの記録
docs/case-study-ieee1800/        IEEE 1800-2023への適用記録と索引
examples/README.md              回路別・方式別の全検証例一覧
examples/                       RTL・検証環境・共通処理・集約ランナー
tools/                          ケーススタディで用いた参照ツール
PROVENANCE.md                   複製元・改訂範囲・実行確認の記録
```

<a id="手法ケーススタディ参照ツール"></a>
<a id="技術ノート検証に使う言語を検証の題材に"></a>

### ケーススタディと由来

SystemVerilogの言語規格を仕様書として、要求の抽出、既存テストとの照合、独立検証、証跡管理に本手法を適用した記録を収録しています。[ケーススタディの索引](docs/case-study-ieee1800/README.md)から、取り込み・同期の基準、確認時点の数値、資料の読む順序、技術ノートへ進めます。

[参照ツール](tools/README.md)はkirimasim-testsの構成を前提としており、このリポジトリ単独では動きません。一般化した手順書と実行例には独自の追記があり、由来と確認範囲は[PROVENANCE.md](PROVENANCE.md)へ記録しています。

<a id="初期の11例の構成"></a>

初期の独自ランナー11例の構成・件数は、[検証例一覧の付録](examples/README.md#初期の11例の構成)に保存しています。共通ランナーや親の集約判定とは別に集計します。

### 今後の計画

1. **手法の改訂**：検証手順書に、ケーススタディで得た知見を反映し続けます。
2. **ツールの汎用化**：要求台帳の形式を、規格の節構成に依存しない形にします。具体的には、要求ID、出典、種別、観測点、構成、証跡を持つ形式です。照合キットを、kirimasim-testsの構成から切り離します。テストやチェッカー、カバレッジ項目に要求IDを付ける方式に合わせたアダプタを用意します。
3. **実際の開発案件での試行**：小規模なIP（レジスタブロックと1つのバスインターフェース）で検証手順を一通り実施し、要求の抽出漏れ、要求とテストの対応付け案の採用率、検出した不具合、仕様上の課題、故障注入時の検出率、工数を評価します。
4. **テンプレート**：検証領域の適用範囲とサインオフ記録の雛形を起点に、要求台帳、照合案、検証者のチェックリスト、課題票を整備します。手順書の台帳例と記録の雛形は運用案であり、現行の照合キットが対応済みの汎用形式ではありません。

### 注意

各例は教材として対象を限定しています。例えば、AXIの例で規格全体への適合、論理CDCモデルで物理的なメタスタビリティ、架空LibertyのSTAで実チップのタイミングを確認したとは扱いません。製品へ適用する際は、仕様・構成と必要な解析・試験を追加して判断します。

- 規格や仕様書の本文は、このリポジトリに入れません。要求は自分の言葉で整理し、出典の版・節・段落を明記します。
- 機密の仕様書を扱う場合は、AIを使える環境と範囲を先に決めます。
- AIによるレビューは、人の承認ではありません。台帳と報告に、担当者と方法を明記します。

## ライセンス

本リポジトリで新規作成した資料・コード、およびkirimasim-testsから複製・改訂した資料・ツールには、Apache License 2.0 with LLVM Exceptions（`Apache-2.0 WITH LLVM-exception`）を適用します（[LICENSE](LICENSE)）。複製元と改訂の記録は[PROVENANCE.md](PROVENANCE.md)を参照してください。

参照先のIEEE規格、外部の文書・ソフトウェアには、それぞれの権利者の利用条件が適用されます。本リポジトリのライセンスは、それらの転載・再配布の許諾を与えるものではありません。
