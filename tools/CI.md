# CIの実行範囲と結果の読み方

GitHub Actionsに、変更時の[Quality](../.github/workflows/quality.yml)と、定期実行の[Nightly verification](../.github/workflows/nightly.yml)を用意しています。ローカルと同じPython入口・登録表を使い、依存の存在確認だけでは合格にしません。

| ワークフロー | 起動条件 | 実行する範囲 |
| --- | --- | --- |
| Quality | push、pull request、手動 | 全文書・Mermaid、toolsのセルフテスト、FIFO・APB・stream・ネイティブSVAのsmoke構成行列 |
| Nightly verification | 毎日UTC 18:23（日本時間翌03:23）、手動 | 全文書、skipなしの全セルフテスト、全例のnightly、全フォーマル・STA・lint、保存結果の履歴照合 |

スケジュールはmainのワークフローを使います。GitHub側の混雑等で開始が遅れる場合があり、時刻どおりの開始を保証する仕組みではありません。`--profile nightly`というランナー引数自体には、定期起動の機能はありません。

## 実行環境

Ubuntu 24.04、Python 3.13、Node.js 24を使います。[環境の準備と診断](ENVIRONMENT.md)でPython・Mermaid・UVM・フォーマルの依存パッケージを導入し、Icarus・Verilator・OpenSTA・CUDDは[`environment.json`](environment.json)のコミットから構築します。Actionsの参照も完全なコミットSHAに固定しています。ネイティブツールのキャッシュは、OS・CPUと構築コード・版台帳のハッシュをキーにします。キャッシュがあっても、環境診断と実際の検証は毎回行います。

ツール取得にはネットワークを使います。OSイメージや全推移依存まで固定する構成ではないため、更新時の診断失敗はログの版と取得先から切り分けます。キャッシュは検証結果の代用ではありません。

## 失敗と証跡

各ランナーが予定件数・必須目標・完了・JUnit・入力ハッシュを判定し、非0終了をジョブの失敗へ反映します。Nightlyは最後に[`regression_report.py`](REPORTING.md)でも保存結果を監査します。JUnitをアップロードするだけで合否を決める構成ではありません。ジョブと子コマンドには時間上限を設けています。

アップロードは`always()`で指定し、失敗したステップより前に作成された証跡も14日間保存します。Qualityの文書ジョブは文書・ツールの証跡を保存し、RTLジョブとNightlyはマニフェスト・summary・JUnit・ログ・入力列・カバレッジDB・反例波形などを選んで保存します。全ビルド生成物・全通常波形・外部ライブラリ本体は容量を考慮して転送しません。転送対象の厳密なパターンはYAMLを参照してください。

ローカルの`runs/`全体とは保存範囲が異なります。失敗の解析で転送対象外の波形や中間ネットリストが必要なら、Actionsで示されたコミット・構成・seedを同じ環境で再実行し、ローカルの完全な証跡を確認します。外部UVM・ネイティブツールの取得元と版・ハッシュはマニフェストと診断に残します。

## 手動実行と確認

GitHubのActions画面でワークフローとmainを選び、Run workflowから実行できます。GitHub CLIを使う場合は次のとおりです。

```sh
gh workflow run quality.yml --ref main
gh workflow run nightly.yml --ref main
gh run list --workflow nightly.yml --limit 5
```

全例の確認にはNightlyの完了を待ちます。Qualityだけの成功は、全例・全フォーマルの成功を意味しません。マージ時に必須にするチェック、PRの承認、Draft、ブランチ保護はGitHub側の運用設定です。このワークフローを置くだけでは設定されません。初回の実行結果とローカルの確認記録は[由来](../PROVENANCE.md#quality-automation-20261101)へ残します。
