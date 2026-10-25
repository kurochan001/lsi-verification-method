# GitLabで割り込みの継続的リグレッションを動かす

有償EDAライセンスを使わず、PythonとIcarus Verilogで動く最小例です。GitLabへこの例を含むコミットを置くと、ランナーの確認テストと、説明用IRQ回路の回帰を実行します。[継続的リグレッションの手順](../../docs/method/continuous-regression.md)を具体的なファイルにしたものです。

## 1. 実行するもの

- [`.gitlab-ci.yml`](../../.gitlab-ci.yml)：下記のCI設定をincludeする入口。
- [`gitlab-ci.yml`](gitlab-ci.yml)：依存ツールの準備、ランナー確認、回帰、JUnit・artifact保存。
- [`run.py`](run.py)：計画生成、コンパイル、ケース実行、判定、manifest・JUnit・結果の作成。
- [`irq_pending.sv`](rtl/irq_pending.sv)：説明用の回路と、検証用に選べる2個の変異。
- [`irq_tb.sv`](tb/irq_tb.sv)：仕様に基づく状態・IRQの比較。失敗ラベルと完了記録を出力する。
- [`test_runner.py`](tests/test_runner.py)：実シミュレーションと異常時のCLI・JUnit判定の確認。

仮の仕様は、イベントでPENDをセット、W1Cでクリア、同時ならセット優先、操作なしは保持、IRQはPENDとIRQ_ENの論理積です。この例はactive lowの**同期リセット**を使います。セット優先はこの例の仕様で、W1C全般の規則ではありません。

通常回路に対して次を実行します。

- 基本動作16ケース：初期PEND 2通り×IRQ_EN 2通り×操作4通り。
- 時間関係の12ケース：初期PEND 2通り×IRQ_EN 2通り×イベントとclearの時間差−1／0／＋1。
- 定期回帰のみ、3個のseedによる64操作ずつのランダム列を追加。

別に、クリア優先へ変えた変異を`IRQ_SET_WINS`で、mask中のイベント保存を止めた変異を`IRQ_SET_ONLY`で検出します。**予定した変異の検出は、この確認項目の成功**です。通常回路の失敗とは区別して結果へ記録します。コンパイル不能や任意のクラッシュを検出成功にしません。

| profile | 通常回路のケース | 変異検出の確認 | JUnitの合計 |
| --- | --- | --- | --- |
| smoke | 28 | 2 | 30 |
| nightly | 31（うち3ケースは各64操作） | 2 | 33 |

ここでの件数はケース単位です。covergroup DBやSVAのcoverageを計測した件数ではありません。Icarusで実行しやすいよう、testbench内の手続き的な比較を使っています。製品IP、UVM、形式検証、CDCの遅延注入、実バス・ソフトウェアの検証は含みません。

## 2. まずローカルで実行する

Python 3.10以上、`iverilog`と`vvp`がPATHに必要です。Debian系Linuxなら、管理権限のある環境で`apt-get update`と`apt-get install python3 iverilog`などにより用意します。Pythonの追加パッケージは不要です。

リポジトリのルートで実行します。

```sh
python3 -m unittest discover -s examples/gitlab-regression/tests -v
python3 examples/gitlab-regression/run.py
python3 examples/gitlab-regression/run.py --profile nightly --seed 17
```

正常なら、ランナー確認の7テストと回帰が合格します。回帰には次のような出力があります。

```text
PASS     atomic-p0-en0-op0: 3 checked cycles
DETECTED detect-clear-priority: expected mutation detected by IRQ_SET_WINS
DETECTED detect-masked-storage: expected mutation detected by IRQ_SET_ONLY
Regression: PASS
```

各実行の出力先は`artifacts/local-日時/`です。`--out`で指定もできますが、古い結果との混同を防ぐため、既存のディレクトリには書き込みません。`artifacts/`はGitの対象外です。

通常回路へクリア優先の不具合を入れるデモは、次です。

```sh
python3 examples/gitlab-regression/run.py --demo-bug 1
```

このコマンドは**終了コード1**になり、通常回路の8ケースが失敗します。JUnitにも8個のfailureが入り、2個の予定した変異検出は別に成功します。失敗を表示しても正常終了してしまうランナーになっていないことを確認できます。

## 3. GitLabへ置いて実行する

GitLab上に空のプロジェクトを用意し、この例を含むコミットをpushします。新規プロジェクトではREADMEなどで初期化しない方法が簡単です。未コミットのファイルはpushでは送られないため、例のファイルを含むコミットを使います。

既存のGitHub向け`origin`を保持し、別の`gitlab` remoteへ送る例です。URLは自分のプロジェクトへ置き換え、GitLabに対応した認証を使います。既存の`gitlab` remoteがある場合は、その設定を確認します。

```sh
git remote add gitlab 'https://gitlab.com/YOUR_NAMESPACE/YOUR_PROJECT.git'
git push gitlab HEAD:main
```

このYAMLの前提は、Linuxコンテナを実行でき、untagged jobを受け付けるRunnerです。GitLab-hostedのLinux Runner、または対応する自社管理のDocker executorなどを使用します。プロジェクトのRunner設定、利用枠、外部イメージ・Debianパッケージを取得できることを確認します。

設定は`debian:bookworm-slim`の中でPythonとIcarusをインストールします。Shell executorでは`image`の環境は使われないため、そのままでは同じ前提になりません。Shell executorへ対応させるなら、ホストへ必要ツールを用意し、`before_script`を採用環境に合わせます。executorごとの対応は[GitLab公式](https://docs.gitlab.com/runner/executors/)で確認できます。

GitLabのpipeline画面で次を確認します。

1. `runner-tests`が合格する。
2. `irq-regression`が合格し、ログ末尾に`Regression: PASS`がある。
3. Tests表示に30項目あり、失敗・errorが0である。
4. `irq-regression`のartifactをダウンロードし、`summary.json`の通常回路28合格・変異2検出を確認する。

プロジェクトのCI Lint／Pipeline editorでも、includeを含む設定を検査します。jobがpendingのままなら、適合するRunner・untaggedの受付・利用枠を確認します。依存パッケージの取得で失敗した場合は環境の失敗で、回路の不具合とは分けます。

## 4. GitLabで赤になるデモ

pipelineを手動で作成するときに、変数`IRQ_DEMO_BUG`を文字列`1`に設定してmainを実行します。画面名は版によりNew pipeline／Run pipelineなどです。

- `runner-tests`は通常の確認を行い、合格する。
- `irq-regression`は通常回路としてクリア優先の誤実装を実行し、終了コード1で失敗する。
- Testsに8個のfailureが表示され、失敗時もJUnit・ログ・波形がartifactへ保存される。

次の正常回帰では`IRQ_DEMO_BUG=0`を使います。デモで失敗したpipelineの記録は残します。変数を1のままスケジュールやプロジェクトの既定へ保存すると、その回帰も意図的に失敗する設定になります。

JUnitのアップロードだけではjobを失敗させられません。この例では、Pythonランナーが失敗・errorを終了コード1へ反映します。[GitLabのJUnit説明](https://docs.gitlab.com/ci/testing/unit_test_reports/)

## 5. 夜間の継続実行

GitLabのPipeline schedulesで、たとえば次を指定します。

- 対象ブランチ：main。
- cron：`0 2 * * *`、タイムゾーン：Asia/Tokyo。
- 変数`REGRESSION_SEED`：`17`など、記録する開始seed。

`CI_PIPELINE_SOURCE`が`schedule`なら、YAMLがnightlyを選びます。通常の28ケースに、開始seed・開始seed+1・開始seed+2の各64操作を追加し、変異確認と合わせて33項目になります。同じ開始seedなら固定した操作列での再確認です。探索seedを変える場合も、スケジュールの設定値とmanifestを保存します。

スケジュールを手動で起動できる機能も使って、33項目になったことを確認します。通常のNew pipelineで起動するとsmokeの30項目です。定期実行の作成・権限・対象ブランチは[GitLab公式](https://docs.gitlab.com/ci/pipelines/schedules/)を参照します。

## 6. 保存するものと判定

CIでは`artifacts/irq/`を失敗時も含めて14日間保存します。

| ファイル | 内容 |
| --- | --- |
| `manifest.json` | 予定ケース、profile・seed・操作列、ソースのSHA-256、Python版、CIのcommit/pipeline/job ID |
| `tools.json`、`*-version.log` | 実際に使ったIcarusとvvpの版表示 |
| `builds.json`、`build-*.log` | 変異ごとのコンパイルコマンド・結果 |
| `summary.json` | 予定・結果の照合、通常回路と変異確認を分けた件数・合否 |
| `junit.xml` | GitLabのTests表示用のケース別結果 |
| ケースごとのディレクトリ | 入力操作列、実行コマンド・状態、ログ、VCD波形 |

予定の全ケースを実行し、正常終了の記録と比較サイクル数、意図した失敗ラベルを確認します。timeout、コンパイル不能、完了記録なし、別の理由による変異の失敗は、成功にしません。通常のランナーでは、どれも集約判定を失敗へ反映します。

この最小例は1個の回帰job内でケースを順番に実行します。分散shard、外部farmの取消、商用ライセンスの全体制御、coverage DBのmerge、要求台帳の自動更新は未実装です。実案件へ拡張する場合は[継続回帰の運用](../../docs/method/continuous-regression.md)に従います。

コンテナのタグとaptのパッケージは、将来同じバイナリを指すとは限りません。この例では実行時のツール版・ソースを記録します。厳密な再現が必要なら、検証済みのイメージを作成しdigest・ツール版を固定します。

## 7. 確認した範囲

2026-10-25にmacOS、Python 3.14.7、Icarus Verilog 14.0 devel（`s20260301-411-gca6b8d376`）で、smoke・nightly・不具合デモとランナーの7テストを実行しました。正常28ケース／nightly31ケースの合格、2変異の検出、デモの8失敗、コンパイラ不足・timeout・完了記録欠落・別checkerによる失敗の分類を確認しています。

GitLab用YAMLは、公開されている[公式JSONスキーマ](https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/assets/javascripts/editor/schema/ci.json)でローカル検査しました。GitLabプロジェクトへのpush、実Runner・Debianコンテナでのpipeline実行、GitLab側のCI Lint・Tests表示・artifactのアップロードは、まだ確認していません。実行先で上記の手順を使って確認します。
