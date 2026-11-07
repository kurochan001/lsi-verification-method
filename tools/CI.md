# CIの実行範囲と結果の読み方

GitHub Actionsに、変更時の[Quality](../.github/workflows/quality.yml)と、変更影響を調べる[Affected verification](../.github/workflows/affected.yml)と、定期実行の[Nightly verification](../.github/workflows/nightly.yml)と、kirimasimの最新版で動かす[Kirimasim latest](../.github/workflows/kirimasim.yml)を用意しています。ローカルと同じPython入口・登録表を使い、依存の存在確認だけでは合格にしません。

| ワークフロー | 起動条件 | 実行する範囲 |
| --- | --- | --- |
| Quality | push、pull request、手動 | 全文書・Mermaid、toolsのセルフテスト、FIFO・APB・stream・ネイティブSVAのsmoke構成行列 |
| Affected verification | push、pull request、手動 | [差分選択](AFFECTED.md#ciの比較基準)した例のsmokeと履歴監査。pushは同じブランチで最後に成功した実行からの差分を見る。不明な依存・共通入力変更は全例へ戻す。文書のみは回路0件と記録 |
| Nightly verification | 毎日UTC 18:23（日本時間翌03:23）、手動 | 全文書、skipなしの全セルフテスト、全例のnightly、全フォーマル・STA・lint、保存結果の履歴照合 |
| Kirimasim latest | 毎日UTC 19:07（日本時間翌04:07）、mainへのpush（例と実行ツールの変更）、手動 | [kirimasim](https://github.com/kurochan001/kirimasim)の`main`の最新コミットで、[Icarus向け80例・107構成](../docs/case-study-kirimasim/README.md)のsmokeを実行 |

スケジュールはmainのワークフローを使います。GitHub側の混雑等で開始が遅れる場合があり、時刻どおりの開始を保証する仕組みではありません。2026-11-01から11-06までのNightlyは、予定の約3時間50分から6時間40分後に作成されました。`--profile nightly`というランナー引数自体には、定期起動の機能はありません。

## 実行環境

Ubuntu 24.04、Python 3.13、Node.js 24を使います。[環境の準備と診断](ENVIRONMENT.md)でPython・Mermaid・UVM・フォーマルの依存パッケージを導入し、Icarus・Verilator・OpenSTA・CUDD・SystemCは[`environment.json`](environment.json)のコミットから構築します。MCY・ネイティブYosys・SBY・ABCは[固定版OSS CAD Suite](ENVIRONMENT.md#oss-cad-suiteの固定版)を別キャッシュで準備し、配布アーカイブと展開内容のハッシュを照合します。Actionsの参照も完全なコミットSHAに固定しています。ネイティブツールのキャッシュは、OS・CPUと構築コード・版台帳のハッシュをキーにします。キャッシュがあっても、環境診断と実際の検証は毎回行います。

ツール取得にはネットワークを使います。OSイメージや全推移依存まで固定する構成ではないため、更新時の診断失敗はログの版と取得先から切り分けます。キャッシュは検証結果の代用ではありません。

Ubuntuの既定ミラーで接続が停滞したため、CIのamd64ランナーにミラー一覧ファイルがある場合は、Ubuntu公式のHTTPS配布元へ切り替えます。通信のタイムアウトは30秒、再試行は最大2回、OS依存の導入ステップは10分を上限にします。インデックス更新は`--error-on=any`で、一部の取得失敗もエラーへ反映します。[APTのミラー一覧](https://manpages.ubuntu.com/manpages/noble/en/man1/apt-transport-mirror.1.html)と[取得失敗の判定](https://manpages.ubuntu.com/manpages/noble/en/man8/apt-get.8.html)はUbuntuの公式資料を参照してください。

ネイティブツールは構築と環境診断が成功した時点でキャッシュへ保存します。後段のセルフテストや回路検証が失敗した場合も、次の実行で診断済みの構築結果を再利用できます。検証の合否は各実行で新しく判定します。

## kirimasimの最新版

他のツールはコミットやハッシュで固定していますが、Kirimasim latestだけは固定しません。kirimasimの変更がこのリポジトリの例で問題を起こしていないかを、早く知るためです。

起動ごとに`main`の先頭を1度だけ調べ、そのコミットをUbuntu 24.04のGCCと`dev`プリセットでビルドします。`dev`は`-O1 -g`にライブラリーのassertを加えた構成で、[2026-11-03の実測](../docs/case-study-kirimasim/README.md)と同じプリセットです。`kirimasim --version`のコミットが一致しなければ、検証へ進みません。バイナリーはコミットごとにキャッシュし、同じコミットならビルドを省きます。[最初の実行](../PROVENANCE.md#kirimasim-latest-ci-20261107)では、ビルドが約8分、smokeが約20分でした。判定には[アダプター](run_kirimasim_examples.py)の監査をそのまま使います。未実装、クラッシュ、タイムアウトがあれば不合格です。

各実行のSummaryには、[`kirimasim_results.py`](kirimasim_results.py)で作った例ごとの表を出します。記録した結果は[実行結果の一覧](../docs/case-study-kirimasim/results.md)にまとめています。

Summaryの先頭には、kirimasimがUVMを処理できるかの確認も出します。[`kirimasim_uvm_check.py`](kirimasim_uvm_check.py)が、固定版のUVMライブラリの解析と`local-uvm`のloweringを試します。107構成の合否には影響せず、UVMの取得に失敗しても「未実行」と表示するだけです。通過したら、[UVM例の実行](../docs/case-study-kirimasim/README.md#kirimasimがuvmに対応したら)を検討します。通過してもメールなどの通知はなく、Summaryと実行の注釈に出るだけです。

kirimasimへのコミットそのものでは起動しません。kirimasimのpushごとに動かすには、kirimasim側にワークフローとトークンを追加する必要があります。

このワークフローが赤くなっても、他のワークフローの合否は変わりません。kirimasim自身のCIが不合格のコミットを試して赤くなることもあります。次の順に切り分けます。

1. 実行のSummaryで、試したkirimasimのコミットと失敗したジョブを確認します。コミットのリンク先で、kirimasim自身のCIの結果も分かります。
2. 同じコミットのAffectedとNightlyを確認します。合格なら、その例はIcarusでは動いています。
3. 前に合格したkirimasimのコミットを指定して再実行します。これも失敗すればこのリポジトリか環境の変更が原因で、合格すればkirimasimの変更が原因です。

```sh
gh workflow run kirimasim.yml --ref main -f commit=<kirimasimの40桁のコミット>
```

## 失敗と証跡

各ランナーが予定件数・必須目標・完了・JUnit・入力ハッシュを判定し、非0終了をジョブの失敗へ反映します。Nightlyは最後に[`regression_report.py`](REPORTING.md)でも保存結果を監査します。JUnitをアップロードするだけで合否を決める構成ではありません。ジョブと子コマンドには時間上限を設けています。

アップロードは`always()`で指定し、失敗したステップより前に作成された証跡も14日間保存します。Qualityの文書ジョブは文書・ツールの証跡を保存し、RTLジョブとNightlyはマニフェスト・summary・JUnit・ログ・入力列・カバレッジDB・反例波形などを選んで保存します。全ビルド生成物・全通常波形・外部ライブラリ本体は容量を考慮して転送しません。転送対象の厳密なパターンはYAMLを参照してください。

画像処理IP・SoCが生成する入力画像、期待画像、ROM、RAM読戻しと、ネットワークIP・SoCの入力／期待フレーム・長さの`.hex`ファイルも保存対象です。退出命令の`retirement.log`と合わせ、画像とソフトウェアの実行条件を確認できます。保存期間後も必要な場合は、コミットと関連する証跡をプロジェクト側へ保管してください。

ローカルの`runs/`全体とは保存範囲が異なります。失敗の解析で転送対象外の波形や中間ネットリストが必要なら、Actionsで示されたコミット・構成・seedを同じ環境で再実行し、ローカルの完全な証跡を確認します。外部UVM・ネイティブツールの取得元と版・ハッシュはマニフェストと診断に残します。

## 手動実行と確認

GitHubのActions画面でワークフローとmainを選び、Run workflowから実行できます。GitHub CLIを使う場合は次のとおりです。

```sh
gh workflow run quality.yml --ref main
gh workflow run nightly.yml --ref main
gh workflow run affected.yml --ref main
gh workflow run kirimasim.yml --ref main
gh run list --workflow nightly.yml --limit 5
```

全例の確認にはNightlyの完了を待ちます。Qualityだけの成功は、全例・全フォーマルの成功を意味しません。マージ時に必須にするチェック、PRの承認、Draft、ブランチ保護はGitHub側の運用設定です。このワークフローを置くだけでは設定されません。初回の実行結果とローカルの確認記録は[由来](../PROVENANCE.md#quality-automation-20261101)へ残します。

SoCLibの例では`systemc-source.json`も保存し、実際にリンクした静的ライブラリー・使用ヘッダー・設定コマンドのハッシュを全体集約時に再照合します。SoCLibのCABAモデルの検証結果と、SystemVerilog RTLのlint・コードカバレッジは別に扱います。

C++参照モデルとSPICE協調も全例の計画に含めます。ngspiceは固定ソースと互換パッチから別キャッシュへ構築し、実APIのRC解析で診断します。`ngspice-source.json`、実行時の回路、CSV、数値誤差、ビルドコマンドも保存します。文書だけの更新では、この回路検証を新たに実行したと数えません。
