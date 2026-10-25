# 継続的リグレッションの計画・実行・結果管理

[一般化した検証手順](spec-to-verification-method.md)の段階Gを具体化した資料です。RTL・検証環境・構成・ツールの変更に対し、繰り返し検証を実行し、失敗・未実行・網羅の変化を追跡します。短い変更時の回帰と、探索・サインオフに必要な広い回帰を計画として管理します。

以下は本リポジトリの運用案です。製品向けの回帰ランナー、GitLab CI/CD、Cadenceの検証管理ツールを導入・接続したものではありません。既存のケーススタディの実行実績とは分けて扱います。

GitLabで試すための[実行可能な最小例](../../examples/gitlab-regression/README.md)を別に用意しています。Icarus Verilogで通常回路・変異を検査し、JUnit・manifest・ログ・波形を保存します。ローカルの動作確認と、GitLab上での確認状況は実行例の末尾に記録しています。

## 1. vManager／Verisium ManagerとGitLabの役割

Cadence vManagerは検証計画・回帰・結果・カバレッジを管理する製品です。現在の公開製品情報では[Verisium Manager](https://www.cadence.com/en_US/home/tools/system-design-and-verification/ai-driven-verification/verisium-manager.html)として、検証計画、API、ジョブの実行・スケジューリング、複数エンジンのcoverage closureなどを説明しています。Cadenceの[技術解説](https://community.cadence.com/cadence_blogs_8/b/fv/posts/enhancing-verification-processes-with-session-composer-a-path-toward-efficiency)でもVerisium Manager（vManager）の名称を使っています。

GitLab CI/CDは、変更・定期実行などからジョブを起動し、Runnerで実行、結果やartifactを集める基盤として使えます。RTLシミュレータや要求台帳・EDAカバレッジの意味付けは、別のツールやアダプタと組み合わせます。CIの成功と、検証要求の完了を対応付ける仕組みはどちらの構成でも必要です。

| 構成 | 担わせるもの | 導入時に確認・用意するもの |
| --- | --- | --- |
| Cadenceの検証管理製品 | 検証計画、回帰、EDAの結果・coverage closureの管理 | 使用版・契約・エンジンとの互換性、要求ID、構成・判定・証跡の運用 |
| GitLab CI/CD＋自社管理Runner | 変更・定期実行の起動、ジョブ実行、結果表示とartifact | EDAランナー、状態の正規化、coverage集計、要求との対応、容量・運用管理 |
| CI＋Cadenceの検証管理 | CIから回帰を依頼し、専用ツール側で管理、結果をCIへ返す | 外部session ID、完了待ち・取消・失敗の伝達、証跡をどこで管理するか |

二者択一にせず、既存の環境と不足する機能で選びます。CadenceのAPIの有無・対応範囲は採用版で確認し、起動要求を受け付けたことだけでCIを合格にしません。外部回帰が完了するまで状態を追い、予定した対象と判定を照合します。

## 2. コストを重視する場合

GitLabと自前の計算資源で運用するRunnerは、有力な開始構成です。GitLabサーバを自社運用する場合と、GitLab.comから自社管理Runnerを使う場合を区別し、ネットワーク・保管場所・管理工数も含めて選びます。[GitLab Runner](https://docs.gitlab.com/runner/)は実行基盤上でジョブを実行するアプリケーションで、計算機の準備・容量・管理は運用側の責務になります。

比較する総費用には、少なくとも次を含めます。

- 検証管理・CIの契約、必要な機能を使えるプラン。
- シミュレータ・形式・coverageなどのライセンスと同時実行枠。
- CPU・メモリ・計算機／クラウド、共有ストレージ、転送・バックアップ。
- CIサーバ・Runner・EDAアダプタの開発、更新・障害対応。
- 失敗の分類・再現、coverage closure、要求と証跡の管理に使う工数。

GitLabのcompute minutesの扱いは、サービス形態・Runnerの種類・設定で確認します。[公式の説明](https://docs.gitlab.com/ci/pipelines/instance_runner_compute_minutes/)では、instance runnerのquotaとproject/group runnerを区別しています。自社Runnerの実行でも、計算資源・EDAライセンス・保存領域が無料になるわけではありません。プランと料金・容量は[料金ページ](https://about.gitlab.com/pricing/)と採用時の契約で確認し、固定の「最安」とは決めません。

すでにGitHubなどで運用している場合は、既存CI＋自社Runnerを続ける費用と移行工数も比較します。このリポジトリはGitHubに置かれていますが、今回の資料追加はGitLabへの移行やCIの有効化を行うものではありません。

## 3. 回帰を段階に分ける

次は頻度の運用例です。時間・構成・test・seed・終了条件は製品の計画として固定し、頻度だけで合格範囲を決めません。

| 回帰 | 起動の例 | 主な対象と確認する結果 |
| --- | --- | --- |
| 変更時の短い回帰 | MR/PR、変更のpush | lint・読み込み、sanity、変更影響のある試験、既知バグの再現 |
| mainの統合回帰 | main更新後 | 統合した版の接続・設定・必須の基本機能、短い固定seed |
| 定期的な広い回帰 | 夜間など | 必須構成の展開、固定＋探索seed、CDC遅延注入、関連するSVA・coverage |
| 資源を使う回帰 | 週次・計画時など | 長時間・高負荷、広い変異集合、重い形式検証、電源遷移など |
| サインオフ回帰 | 対象版を固定した時点 | 承認した必須計画一式、最終版の結果と未達・例外の照合 |

GitLabでは[scheduled pipeline](https://docs.gitlab.com/ci/pipelines/schedules/)などを使えます。予定時刻の設定だけでなく、実際に起動したこと、対象commit、予定ケース、終了と結果収集まで監視します。起動されなかった回帰は、失敗が0件でも未実行です。

影響に基づく選択やseedの縮約は、[検証規模の縮退](verification-reduction.md#6-回帰テストとseedを縮約する)に従います。新しいseedでの探索と、失敗を再現する固定seedの両方を持たせます。変更時の小さい回帰が通ったことを、定期・サインオフ回帰の合格へ読み替えません。

## 4. 計画・ビルド・分散実行を同じ回帰へ結ぶ

回帰を起動するときに、実行対象の一覧を持つmanifestを確定します。campaign ID、計画版、commit、構成、test・scenario、seed、checker、ツールと入力、必要なcase IDを記録します。実行中に対象を追加・削除する場合も、計画の変更として残します。

処理の順序は、次を基本にします。

1. 入力と計画を検査し、必須ケースの一覧を確定する。
2. 構成・ツール・マクロ・パラメータごとにビルドし、そのID・ハッシュを保存する。
3. case IDを分割して実行する。各shardへ担当ケースを渡し、同じケースが欠けたり意図せず重複したりしないようにする。
4. 個別の結果・ログ・証跡を回収し、予定ケースと結果を突き合わせる。
5. 元の結果を保持したうえで必要な再実行・分類を行い、回帰全体の判定を出す。
6. 互換なcoverage DBを集計し、要求・構成・未達・傾向へつなぐ。

Runnerや外部farmのジョブIDは、campaign・case・attemptのIDと対応付けます。retryには別のattempt IDを付け、最初の失敗を上書きしません。別のcommitや計画の部分結果を混ぜて、同じ回帰が合格した記録を作りません。

ビルドcacheには、ソース・生成物・ツール・ライブラリ・構成・コンパイル条件など、生成結果に影響する入力を反映します。cacheを復元できたことを、正しい版を検証した根拠にはせず、使用したビルドの入力とIDを照合します。

## 5. 資源・ライセンス・待ちを制御する

並列数は、CPU・メモリ・ライセンス・I/O・外部farmの上限に合わせます。CIのジョブ数だけでは、他プロジェクトや手動実行との合計を制御できない場合があります。共有farmやライセンスの制御は、必要な範囲全体で上限を守る仕組みへつなぎます。

待ち行列、ライセンス待ち、ビルド、シミュレーション・solver実行、結果収集の時間を分けます。応答モデルが規定のサイクル期限を超えた失敗と、ライセンス不足・Runner停止・計算機の実時間制限を区別します。実時間制限・メモリ超過では、途中までの結果と終了理由を可能な範囲で保存し、未完了として扱います。

古い変更時回帰を取り消す運用では、取消を記録し、後続の回帰がどの計画を引き継ぐかを確認します。取消が外部farmのジョブまで伝わったかも追跡します。サインオフ回帰など、対象版と完了を維持する必要がある実行は、変更時回帰と別の取消方針にします。

## 6. テストの状態とCIの状態を対応付ける

ランナーはツール固有の結果を、合格・失敗・判定不能・未実行・承認された対象外へ対応付けます。少なくとも、次を検査します。

- 終了コード、UVMのerror/fatal、SVA失敗、scoreboardの不一致と未照合、比較件数、予定した正常な終了。
- 形式検証のmodeと最終状態、必須プロパティとcover、仮定・境界。`unknown`・timeoutを合格へ移さない。
- manifest上の必須ケースすべてに結果があり、途中終了・未起動・結果ファイル欠落がないこと。
- 意図した診断や変異検出が合格条件になる試験では、その期待結果が成立したこと。任意のクラッシュを期待失敗の成功としない。

GitLabの[JUnitレポート](https://docs.gitlab.com/ci/testing/unit_test_reports/)は結果表示に使えますが、XMLを登録しただけではjobの成否は変わりません。必須の失敗・未完了・結果欠落を、集約処理の終了状態へ反映します。`allow_failure`や失敗を無視するシェル処理で必須検査を成功へ変えないよう、ランナー自体も確認します。

JUnitの名前には、testだけでなく必要な構成・seed・case IDを含め、同名結果の欠落を避けます。判定不能を単にskippedへ変換して完了数へ足しません。詳細な状態は元の実行記録へ残し、JUnitは表示用の対応として使います。

小さなランナー確認では、正常、checkerによる失敗、ビルド不能、timeout、必須結果の欠落、再実行、外部回帰の起動後の失敗を意図的に作り、CIが計画どおり判定するかを確かめます。本資料では、そのランナーの実装・実行は行っていません。

## 7. 失敗の再現・分類と不安定な試験

最初の失敗について、commit・ビルド・test・構成・seed・入力・モデル・ログ・波形・実行場所を保存し、同じ条件で再現します。DUT、仕様・期待値、checker、制約、環境・資源・ツールへ原因を分け、代表ログ・失敗ラベルなどでまとめます。似たメッセージだけで同じ原因と断定せず、個別のcase IDを保持します。

再実行で通る不安定な試験は、最初の失敗と再実行の結果を併記して課題化します。「通るまでretry」では閉じません。環境障害の自動再実行には対象理由と上限を決めます。隔離が必要なら、対象要求・期間・担当・代替検査・承認を記録し、技術的な合格や対象外へ移しません。

検出した不具合は、[失敗の縮小](constrained-random-verification.md#8-失敗を再現し縮小して回帰へ残す)と修正後の確認を経て、再現する直接テストや固定seedを回帰へ加えます。連絡・課題登録の担当と期限も運用計画へ含めます。

## 8. coverage・証跡・傾向を保存する

各caseの判定とcoverage採取・DB生成を別に確認します。合格しても必要なDBがない、checkerが無効、比較件数が0という状態は、その目的の検証完了にしません。失敗runの到達情報を診断へ使う場合は、合格証跡に使う集計と分けます。

DBを統合するときは、RTL・モデル・ツール・構成・指標・除外の互換性を確認し、元のrun IDを残します。coverageの集計・除外は[機能網羅](functional-coverage.md)と[コードカバレッジの未達分析](verification-gap-review.md#10-コードカバレッジの未達を閉じる)に従います。テスト結果、coverage、要求の合格、例外承認は別の指標として報告します。

通常の実行で残すものはmanifest、個別結果、判定ログ、ツール・入力の版、coverageと集計元です。失敗・重要ケースの波形や再現入力、サインオフの証跡は、保存期間と場所を決めます。大きい波形を全runで無制限に保存せず、再現性・調査・承認に必要なものを残します。

GitLabのartifactを使う場合は、失敗時にも必要な結果を収集する設定と、保持期限を確認します。強制停止やRunner障害で回収できない場合もあるため、必須証跡の欠落を集約処理が検出するようにします。CIの一時artifactだけに、長期保存が必要な承認証跡を依存させません。

傾向には、予定・完了・合格・失敗・判定不能・未実行、構成別の要求・coverageの未達、失敗の再発、待ち・実行時間、CPU・メモリ・保存量を表示します。テスト・目標・分母が変わった場合は、共通部分と新規・削除分を分け、単純な合格率の改善と混同しません。

## 9. 最小構成から始める

コストを抑える開始案は、既存のGit管理＋CI、自社管理Runner、CLIで再現可能なEDAランナー、manifest・結果記録、JUnit変換、ログ・coverageの保管です。最初に短い固定の回帰を成立させ、次に定期回帰・探索seed・構成の展開を追加します。

CI設定からツールのコマンド・判定を直接大量に埋め込む前に、同じmanifestをローカルやfarmで再実行できるインターフェースを定めます。CIや検証管理製品を変えても、要求ID・case ID・入力と結果の関係を追跡できるようにします。

必要なcoverage closure・多数の利用者・構成・拠点を管理する工数が大きくなったら、専用の検証管理製品との統合を比較します。評価には同じ代表回帰を使い、設定・失敗解析・coverage対応・運用の工数、待ち時間・実行量・費用を測ります。導入費だけの比較で決めません。

## 10. サインオフへ接続する

回帰の完了には、固定したmanifestに対して必須ケースの結果がそろい、判定とcoverage・証跡が有効であることが必要です。fail数0だけでなく、未実行・判定不能・結果欠落・checker無効・古い版・未承認の隔離を確認します。

記録には、CIと回帰計画の版、campaign・pipeline・外部session ID、予定と実行の対応、retry履歴、集約判定、coverageの統合元、長期証跡、未達・例外、担当・承認を含めます。既存の同じ実行回で判定するAND集合の規則を維持し、[サインオフ記録](../templates/signoff-record.md)へつなぎます。

## 11. 参考にした一次資料

- [Cadence Verisium Manager](https://www.cadence.com/en_US/home/tools/system-design-and-verification/ai-driven-verification/verisium-manager.html)と[Session Composerの技術解説](https://community.cadence.com/cadence_blogs_8/b/fv/posts/enhancing-verification-processes-with-session-composer-a-path-toward-efficiency)：検証計画・回帰・coverage管理とvManagerの名称の参照先です。
- [GitLab Runner](https://docs.gitlab.com/runner/)、[定期pipeline](https://docs.gitlab.com/ci/pipelines/schedules/)、[JUnitレポート](https://docs.gitlab.com/ci/testing/unit_test_reports/)、[CI設定](https://docs.gitlab.com/ci/yaml/)：起動・実行・結果表示・artifactの参照先です。
- [GitLabのcompute minutes](https://docs.gitlab.com/ci/pipelines/compute_minutes/)、[instance runnerの使用量](https://docs.gitlab.com/ci/pipelines/instance_runner_compute_minutes/)、[料金](https://about.gitlab.com/pricing/)：2026-10-25に確認した費用・quotaの参照先です。採用時に再確認します。

回帰の段階、manifestと結果の照合、判定・証跡・費用の評価方法は、本リポジトリで定めた運用案です。
