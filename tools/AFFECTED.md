# 変更箇所から実行する検証例を選ぶ

[`select_regression.py`](select_regression.py)はGitの差分とレビュー済みの[依存台帳](regression_dependencies.json)から影響する例を選びます。選択理由・全例への切替理由・予定ジョブ・実際の実行数を保存します。定期実行の[全例nightly](CI.md)を減らす機能ではありません。

## 選択の規則

| 変更・状態 | 選択 |
| --- | --- |
| 既知の例のRTL・テストベンチ・ランナー・実行時仕様データ | 所有する例と、その例に依存する消費側を推移的に選択 |
| 共通DUT | lint台帳の共有関係から消費側と共通lintを選択 |
| tools・workflow・テンプレート・依存パッケージ・未分類の入力 | 全例 |
| 実行入力の追加・削除・改名、依存関係の変更、台帳との不一致 | 全例。台帳をレビューして更新 |
| baseのコミットを取得できない | 全例 |
| 説明文書・READMEだけ | 回路ジョブ0件。文書・ツール検査はQualityで実行 |
| 差分なし | 回路ジョブ0件 |

台帳には例の実行入力一覧、ソース内の明示的な別例への参照、登録表の親子関係、lintの共有DUTを記録します。一般のPythonプログラムの依存を完全に解析するツールではありません。動的に組み立てる参照・外部入力を追加するときは、全例へ戻す共通入力にするか、依存抽出と負例テストを更新してください。実行されるテンプレートや例内の仕様Markdownは、説明用READMEと区別しています。

## ローカルで計画・実行する

```sh
# 差分から計画だけを作る。回路は動かない
python3 tools/select_regression.py --base origin/main --out artifacts/affected-plan

# 未コミットの変更も明示的に含める
python3 tools/select_regression.py --base HEAD --include-worktree \
  --out artifacts/affected-worktree

# 選択した例を新しく実行し、保存結果も監査する
artifacts/toolchains/full/python/bin/python tools/select_regression.py \
  --base HEAD~1 --run --out artifacts/affected-run -- \
  --jobs 2 --command-timeout 60 --formal-timeout 1800 --child-timeout 7200 \
  --build-timeout 600 \
  --python "$PWD/artifacts/toolchains/full/python/bin/python" \
  --formal-python "$PWD/artifacts/toolchains/full/formal/bin/python" \
  --rdl-python "$PWD/artifacts/toolchains/full/python/bin/python" \
  --cocotb-python "$PWD/artifacts/toolchains/full/python/bin/python" \
  --uvm-home "$PWD/artifacts/toolchains/full/uvm/1800.2-2020.3.2" \
  --oss-home "$PWD/artifacts/toolchains/full/oss/oss-cad-suite" \
  --tool-bin "$PWD/artifacts/toolchains/native/install/bin" \
  --tool-bin "$PWD/artifacts/toolchains/ngspice/install/bin"
```

`--head`はチェックアウト中のHEADに限ります。作業ツリーに変更がある場合は、`--include-worktree`を省くと失敗します。`--`以降はツールの配置先・時間上限・並列数だけを許し、例・seed・プロファイル等の選択を上書きできません。

`--run`の実行中にSIGTERMまたはSIGINTを受けるか`--execution-timeout`に達すると、全体ランナーと、例が別セッションで起動したプロセスまで停止します。割込みの終了コードは143と130です。全体ランナーを強制停止するため、キャンペーンの`summary.json`は途中の内容（`complete: false`）か未作成のままで、合格にはなりません。

親と子を選んだ場合は[全体ランナー](REGRESSION.md)が重複を除き、構成行列も維持します。実行前に固定したジョブIDと実際のマニフェストを照合し、[履歴監査](REPORTING.md)が成功することを要求します。以前の結果を新しい実行として流用しません。

## 結果の意味と台帳更新

`selection.json`の`status`、`changed`、`reasons`、`full_reasons`、`selected_jobs`、`executed_jobs`、`execution_skipped`を確認します。実行しない場合、`summary.json`と`junit.xml`に`execution`・`audit`の判定は現れず、理由を`execution_skipped`に残します。`executed_jobs`は、統合ランナーが実際に起動したルートジョブの数です。起動前の依存不足を数えず、起動後の失敗・時間切れ・中断は起動済みとして記録します。シミュレーションや子タスクの件数とは区別します。`hardware_verified`は、全選択ジョブの実行・監査・終了時の入力照合が成功した場合だけtrueです。計画のみ・文書のみ・差分なしはfalseです。選択自体の成功を、全例の合格と読み替えません。実行途中の入力の変更・追加・削除も失敗にし、`hardware_verified`をfalseにします。

| 状態 | `selected_jobs`の件数 | `executed_jobs` | `hardware_verified` |
| --- | --- | --- | --- |
| 文書のみ・差分なし | 0 | 0 | false |
| 選択計画のみ | n（1以上） | 0 | false |
| 起動前の不足・実行失敗・監査不合格 | n（1以上） | 0〜n | false |
| 全選択ジョブの実行・監査・終了時照合が成功 | n（1以上） | n | true |

同じ`executed_jobs=n`でも、起動したジョブが失敗すれば検証済みにはなりません。表のnは選択したルートジョブ数で、全例の件数や子のテスト件数ではありません。

例や依存を追加したら、次で候補を生成し、差分をレビューします。台帳だけを更新して影響するテストを省略する判断には使いません。

```sh
python3 - <<'PY'
import json, sys
sys.path.insert(0, 'tools')
import select_regression as s
entries = s.R.load_registry(s.HERE / 'regressions.json')
s.DEPENDENCIES.write_text(json.dumps(s.dependency_inventory(s.Q.ROOT, entries), ensure_ascii=False, indent=2) + '\n')
PY
```

[変更時のAffected CI](../.github/workflows/affected.yml)はこの選択をsmokeで実行します。不明な変更はsmokeの全例へ戻し、毎晩は全例をnightlyで実行します。Qualityの代表4例も継続して実行します。

## CIの比較基準

| イベント | `--base`に渡すコミット | 実行中の同じ参照への新しい実行 |
| --- | --- | --- |
| pull request | `base.sha` | 古い実行を取り消す |
| push | 同じブランチのpushで最後に成功したAffectedのコミット。空、またはHEADの祖先でなければ`github.event.before` | 取り消さず待たせる |
| 手動 | `HEAD~1` | 取り消さず待たせる |

基準は最初のステップで一度だけ決め、選択と実行の両方で同じ値を使います。pushごとの差分だけを見ると、失敗したpushや、待機中に新しいpushへ置き換えられた実行の変更が、次のpushの差分に入りません。文書だけの次のpushが回路0件で成功する形にもなります。GitHubの`concurrency`は待機中の古い実行を取り消すため、取消しをやめるだけでは足りず、成功した実行を起点にします。起点を調べるために`actions: read`を使います。

新しいブランチの最初のpushなど`github.event.before`を解決できない場合は全例です。成功履歴を取得できない場合は警告を出して`github.event.before`を使うため、そのpushの差分だけの確認になります。手動実行は最新コミットの差分だけを見るので、失敗後の確認には全例のNightlyを使います。
