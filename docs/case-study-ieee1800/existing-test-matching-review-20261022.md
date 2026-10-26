# 既存テストの要求照合で見つかった問題（2026-10-22開始、2026-10-23更新）

対象は既存テストと IEEE 1800-2023 の要求台帳との対応です。
全テストの意味上の照合を完了したという報告ではありません。
[全テストの照合台帳](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/test-requirement-matching.md)と
[現在の計測結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/behavior-coverage-summary.md)を併せて参照してください。
最新の続行結果は[未登録テストの照合（2026-10-25）](existing-test-matching-unregistered-20261025.md)です。

## 今回の到達点

- 全3,938本について、引用節による未承認候補と入力ハッシュを照合台帳に登録しました。
- 対応登録済みテストは55本から1,386本、対応済み要求行は114行から2,465行になりました。
  一つ以上の観測を対応付けた本数で、1,386本すべての観測・要求を精査済みという意味ではありません。
- 未登録の2,552本を残件として管理しています。全件の意味上の照合は未完了です。
- 保存済みの全3,912本のIcarus 13.0／Verilator 5.052の実行結果と、追加・引用変更したテストの別実行結果を利用しました。
  部分実行を全3,938本の一括再実行とは扱っていません。
  既知不一致を成功に含めていません。成功件数はリンク先の集計と実行証跡を参照してください。
- 登録行に対する暫定の設計網羅率は20.009741%（2,465/12,319）、実行確認率は10.49%（1,292/12,319）です。
  確定値は引き続き未確定です。
  複数テストの分担を扱う計測規則3を使用し、履歴に規則の版と分母の識別子を残しました。
- 既存テストの刺激・期待値・要求定義は変更していません。以前の7本、サブルーチン照合時の4本に加え、連想配列照合時の7本の`:lrm:`引用だけを具体化・訂正し、更新後に再実行しました。
  M01以降で示す刺激・期待値・判定の問題は、この照合では変更していません。

## 最新の続行結果（2026-10-26）
2026年10月25日から26日に、検証待ちだった残りの区間をすべて検証して取り込みました。
- 照合案：p01・p05・p07・p12は402件中397件、p09・p10・p13・p15は473件中461件、附属書とgapの範囲（a01〜a05、g05、g08、g09、h01、h02）は513件中507件を採用しました。
- テスト：検証を通った新規テスト（256本、188本、176本）を加えました。検証で欠陥とされたテストは、直せるものを直し（`var`を省いた入力ポート、エラーの行番号、`:oracle:`の記載など）、意味の上で誤りのあるものは外しました。
- 追加のテスト：K.2・I.3・N.2の要求に18本、アサーション制御・カバレッジ・checker・1364 VPIに30本を書き、独立検証を経て加えました。附属書Aの構文テストは、照合案517件から369件の対応と93本のテストを取り込みました。
- `:oracle:`：規格だけを根拠にしていたテストのうち、Icarus 13.0が期待どおりの出力・診断を再現する277本に`iverilog@13.0`を記録し、再実行しました。
- 既存テストの照合：12の範囲で候補のテストを独立にレビューし、341要求を対応付け、要求の一部しか観測しない1,392件を保留として記録しました。

集計は9,585要求（77.80664%）、成功証跡5,424要求（44.029548%）で、75%の目標を超えました。本文（1〜40章）だけでは77.46%です。

## 2026-10-24の続行結果
[未対応要求への新規テストの2回目](gap-tests-2-20261024.md)で、中断していた8区間の作成を再開し、独立検証を終えた新規テスト933本と照合案を取り込みました。
集計は7,341要求（59.590876%）、成功証跡4,135要求（33.566036%）です。本文（1〜40章）だけでは62.57%です。
検証では照合案1,030件のうち102件を却下し、新規テスト962本のうち26本を欠陥としました。
新しい種類の欠陥として、`` `line ``と同じ行に置いたコメントが22.12の違反を重ねる例と、仮想インターフェースを種類なしの入力ポートにする例がありました。

その前の2026-10-24の結果です。
[未対応要求への新規テスト](gap-tests-20261024.md)で、独立検証を終えた13区間の新規テスト594本と照合案を取り込みました。
集計は6,430要求（52.195795%）、成功証跡3,734要求（30.310902%）で、50%の目標を超えました。本文（1〜40章）だけでは53.47%です。
検証では照合案2,215件のうち166件を却下し、新規テスト624本のうち30本を欠陥としました。
2状態型の入力ポートを種類なしで宣言する形（`input int`、23.2.2.3と6.7.1によりネットとなり違法）が、取り込み分の1本（修正済み）と既存テスト7本（未修正）にありました。

その前の2026-10-24の結果です。
[要求抽出の台帳見直し](requirement-extraction.md)で予約語の行を違法系に組み替え、27件の解釈保留を解消しました。
続く[予約語の違法系テストの生成](keyword-tests-20261024.md)で496本の生成テストと497要求の対応を追加し、
集計は4,386要求（35.603539%）、成功証跡2,893要求（23.484049%）です。本文（1〜40章）だけでは31.92%です。

## 2026-10-23の続行結果
[附属書ヘッダ・VPIテストの追加と照合](header-vpi-tests-and-matching-20261023.md)で、独立検証を終えた分を取り込みました。
集計は3,889要求（31.569121%）、成功証跡2,396要求（19.449631%）です。附属書I/K/L/MのCヘッダを検証する新規テスト24本（1,081要求）、
37章のVPI新規テスト24本（193要求）、既存テストの照合150要求と、M98–M129の32件の保留判断を追加しました。
増分の大半は附属書の定数行で、本文（1〜40章）だけでは29.30%（2,779/9,486）です。50%の目標には未達で、検証前の分は取り込んでいません。

以下は、その前の20%到達時点の記録です。
[20%超過の照合結果](existing-test-matching-20percent-20261023.md)で今回の目標を達成しました。
集計は2,465要求（20.009741%）、成功証跡1,292要求（10.487864%）です。全テストの意味上の照合は引き続き未完了です。
418本から1,296件の根拠を追加し、要求定義・分母・既存入力を保持しています。M65–M97と42件の保留判断を追加しました。最終監査で既存保留と不整合な仮対応20件を除外し、別fixtureの20件へ置き換えた結果です。

前回の[VPIの照合・10%到達結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-vpi-20261023.md)では、
55本から442件の対応根拠を追加し、対応要求は810行から1,242行（+432行）になりました。
暫定設計網羅率10.081987%で、10%超過を確認しました。実行確認は754行、6.12%です。
M59–M64と39件の範囲別判断、5件のAND集合証拠を記録しました。既存入力・要求定義は保持しています。
元テストの再実行は行わず、保存済み結果へ入力・ランナーの鮮度を照合しました。
その直前の[コンパイラ指令のレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-preprocessor-20261023.md)では、
32本・18要求行・85件の対応根拠を追加しました。M52–M58、5件の集合証拠と41件の範囲別判断を記録しています。
既存の刺激・期待値・メタデータを変えず、保存済み実行証跡へ現在の入力ハッシュを照合しました。
新規18要求行すべてに成功証跡があります。元テスト全件の再実行や新規テスト追加ではありません。
その直前の[連想配列の不足した観測へのテスト追加](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/associative-gap-tests-20261023.md)では、
M45–M50を受けて15本の新規テスト、24要求行・28件の対応根拠を追加しました。
Verilator 5.052のseed 1/73で8本一致・7本known、Icarus 13.0で15本knownです。
実行確認済み要求は12行増えました。更新後の入力の実測結果だけを採用しています。
その直前の[連想配列のレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-associative-arrays-20261023.md)では、
35本・22要求行・74件の対応根拠を追加しました。M44–M51、12件の集合証拠、7本の引用修正と40本の再実行を記録しています。
その直前の[配列メソッドのレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-array-methods-20261023.md)では、
35本・21要求行・119件の対応根拠を追加しました。M36–M43と保留理由、8件の集合証拠を記録しています。
その直前の[クラス・構築・メソッドのレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-classes-20261023.md)では、
45本・27要求行・92件の対応根拠を追加しました。M29–M35と保留理由、3件の集合証拠を記録しています。
その直前の[制御文・ループのレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-control-flow-20261023.md)では、
51本・26要求行の対応を追加しました。M23–M28、集合証拠、実行証跡と保留理由を記録しています。
その直前の[不足した観測へのテスト追加](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/expression-gap-tests-20261023.md)では、
M18–M22を受けて11本の新規テスト、29要求行の対応を追加し、更新後の入力で実行しました。
その直前の式・幅・符号・算術の照合では29本・42要求行の対応を追加しました。
[式と算術のレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-expressions-20261023.md)に、
M18–M22、べき乗の集合証拠、未採用の理由と実行証跡を記録しています。
その直前の42本・27要求行の追加は[サブルーチンのレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-subroutines-20261023.md)、
さらに前の43本・41要求行の追加は[代入系のレビュー結果](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/existing-test-matching-review-20261023.md)を参照してください。
照合分では既存入力・期待値を変更せず、追加分は新規テストとして記録しています。
要求定義は変更していません。以下は2026-10-22時点の経過と指摘です。

## 前回の続行分の照合と検査（コミット0e9cc29時点）

直前の410本・386行から、文字列、動的配列、キュー、列挙型、型変換、違法系の型・クラス制約、
生成されたx/z伝播・シフト・縮約演算を照合し、597本・493行に増えました。
直前からの増分は187本・107行です。要求の全12,319行の定義・合格基準は変更していません。

対応を保留した31本・32件の範囲別判断を
[レビュー判断台帳](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/coverage/test-matching-reviews.json)へ記録しました。
部分観測、期待値／診断の問題、引用の具体化、複合要求の整理を区別しています。
入力ハッシュと根拠文字列を検査し、古い判断を検出します。
この件数はファイル全体のレビュー完了数ではなく、カバレッジの分子にも加えません。

以下の7本は、刺激・期待出力を保ったまま引用を具体化し、両シミュレータで再実行しました。
各ファイルは少なくとも一方で成功し、既知不一致・未対応を成功としていません。

- `ch15/test_semaphore_multiple.sv`: 15.3.1–15.3.4。
- `ch6/test_enum_method_edge.sv`: next/prev/num/nameの個別節。
- `ch6/test_enum_methods_navigation.sv`: 列挙型のナビゲーション・nameの個別節。
- `ch6/test_enum_methods_name_num.sv`: 6.19.5.5–6.19.5.6。
- `ch6/test_enum_explicit_cast_and_failed_dynamic_cast.sv`: 6.24.2。
- `ch7/test_dynamic_array_edge_cases.sv`: 7.5.1–7.5.3。
- `ch7/test_dynamic_array_corner.sv`: 7.5.1。

全スイート実行後の引用変更なので、以前の入力ハッシュを成功として再利用せず、
`citation-refinement-icarus.json`と`citation-refinement-verilator.json`へ7本の再実行を保存しました。
全スイートのスナップショットを部分実行で上書き・合成していません。
複合証拠の要求は現在7行で、同じ実行回のグループ全成功だけを採用します。

管理ツールの74テスト、生成物の整合検査、規格資料のハッシュ照合、対応根拠の鮮度検査を実施しました。
元の刺激・期待値との差分がないことも機械的に確認しています。

## 2026-10-22の続行分：プロセス・イベント・終了処理

前回の597本・493行から、637本・533行へ増えました（40本・40行の増分）。
新たな対応根拠は65件です。主に9章のイベント式、iff、forkの開始・終了、wait fork、
disable、processの状態、always_combの感度、およびfinalの終了経路を照合しました。
4.4.2.3の#0処理、35章のDPIテストによる暗黙終了、36章のVPI終了コールバックも確認しました。
DPI/VPIについては関連するCファイルも読み、実際の呼び出しと出力を確認しています。

今回のテスト入力は変更していません。既存の全スイート実行の入力ハッシュと成功結果を照合し、
実行確認済み要求は448行から483行へ増えました。
追加の40行のうち5行は実行成功の証拠がそろわず、設計対応のみです。
既知不一致・未対応を成功へ読み替えたり、今回シミュレータを再実行したと扱ったりしていません。
全12,319行の要求定義・合格基準と分母の識別子も変更していません。

今回追加した集合証拠は、直接の子と終了済み中間親の子孫のdisable fork、
名前付きブロックとタスクからの継続、入れ子タスクとfork子孫の終了、
明示／暗黙の終了によるfinal、既に真／後で真となるwaitの5要求です。
集合証拠の要求は合計12行になりました。一つの部分テストだけの成功を行全体の成功にはしません。

保留理由は累計53本・56件へ増えました（今回22本・24件を追加）。
この件数は範囲を限定した判断で、ファイル全体の精査完了数ではありません。
M07・M08に新しい観測不足を示しました。
また、正常終了待ちだけのawait、子孫を持たないkill、時間観測のないbegin/end、
具体的な子節引用が不足する感度テストなどを、理由付きの残件として保持しています。

管理ツールの74テストと、要求対応・規格資料ハッシュ・生成物・メタデータの整合検査を実施しました。

## M01: $isunbounded に数値リテラルを渡す正常系テスト

対象: [test_system_isunbounded.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch20/test_system_isunbounded.sv)。

`$isunbounded(100)` の戻り値ゼロを正常な期待結果として要求しています。
規格20.6.3の本文と Syntax 20-8（提供PDFの物理631ページ）は、引数をパラメータ名に制限しています。
したがって、この呼び出しを拒否する実装を不合格にする現在の期待値は不適切です。
既存シミュレータが受理することだけでは、この刺激を規格準拠にはできません。

正常系では `localparam int FINITE = 100` などを宣言して名前を渡してください。
リテラルを渡す場合の拒否を検証するなら、正常系から分離して違法系にします。
現状のファイルは20.6.3の対応として承認していません。テスト本体と期待値は変更していません。

## M02: 宣言・名前だけでは、その機能の検証にならない

例: [test_macro_concat.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch22/test_macro_concat.sv) は
`MAKE_NAME(base)` に二重バッククォートによる名前連結を定義しますが、呼び出していません。
`STRINGIFY` の結果、宣言マクロ、ネストした数値マクロの観測はありますが、
この名前連結の定義だけを `MACRO-TOKEN-DELIMITER` の検証に計上してはいけません。

また [test_macro_advanced.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch22/test_macro_advanced.sv) の
`STRINGIFY` と `CONCAT` も定義だけです。
実際に呼び出し、組み立てた識別子へのアクセスや、展開文字列の期待結果を観測する必要があります。
今回の登録では、これらの未使用定義を根拠とする対応を追加していません。

## M03: 複合要求と正常／違法の区分により、そのまま承認できない行

これはテスト不存在の指摘ではなく、要求台帳側の分割・整理の残件です。
たとえば `SV2023-22.8-EXTRACT-NETTYPE-DEFAULT-NONE` は、
既定の暗黙wireと、`default_nettype none` による未宣言net禁止を一行にまとめています。
`kind: error` のため、暗黙wireを観測する正常系だけでは、この行全体への対応を登録できません。

[test_resetall_default_nettype.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch22/test_resetall_default_nettype.sv) には
reset後の暗黙netが幅1のwireとして機能する観測があります。
この検証価値を無視せず、正常系と違法系を独立した要求単位に分割して対応付ける必要があります。
分割は出典・分母・基準値の変更を伴うため、今回の照合で要求を緩和したり分母から除外したりしていません。

また、[test_semaphore_blocking_keys.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch15/test_semaphore_blocking_keys.sv) の
「初期2鍵から `put(3)` 後に2鍵取得できる」という観測だけでは、
初期値を超える容量や、取得後に正確に1鍵残ることは確認できません。
実装が2鍵へ切り詰めたり余分に消費したりしても、その後の2鍵要求はどちらも失敗します。
待機・解除の検証価値はありますが、この観測を残数保存や容量無制限の要求全体へは対応付けていません。

## M04: semaphore.try_get の成功を正確な1に限定した期待値

対象: [test_std_package_access.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch26/test_std_package_access.sv) と
その [期待出力](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch26/test_std_package_access.expected)。

`s1.try_get()` をそのまま表示し、期待出力を `semaphore: 1, std::semaphore: 0`
としています。規格15.3.4（提供PDFの物理374–375ページ）は成功時の戻り値を
「正の整数」と定義し、正確な1には限定しません。
例えば成功時に2を返す実装でも規格に適合しますが、現在のテストは不一致になります。

成功判定は `s1.try_get() > 0` に正規化し、失敗側は0を検査してください。
このファイルは標準パッケージの参照・隠蔽を観測していますが、
この期待値の問題を含む現状では、そのまま対応を承認していません。
テスト本体と期待値は変更していません。

## M05: string.compare の非ゼロ結果を正確な -1 に限定した期待出力

対象: [test_string_methods_extended.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch6/test_string_methods_extended.sv) と
その [期待出力](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch6/test_string_methods_extended.expected)。

`"abc"` と `"abd"` の比較結果をそのまま表示し、`Test 7 PASS: compare=-1` を要求しています。
規格6.16.6は、大小関係に応じた負・ゼロ・正を規定し、非ゼロの絶対値を固定しません。
例えば -2 を返す適合実装も、現在の期待出力では不合格になります。
さらにテスト内の判定は `!= 0` なので、正の値という誤った大小関係も内部判定では通ります。

内部判定を `< 0` にし、成功出力では比較結果の符号だけを観測するようにしてください。
このファイルの他の文字列操作にも検証価値がありますが、現状の期待値を持つファイルは
要求対応の承認を保留しています。テスト本体と期待値は変更していません。

## M06: 違法系の行番号一致だけでは、意図した違反の検出を確認できない

例: [test_illegal_interconnect_data_type.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch6/test_illegal_interconnect_data_type.sv) と
[test_illegal_ref_in_static_function.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch13/test_illegal_ref_in_static_function.sv)。

現在の違法系ランナーでは、エラー行が `expected_stderr_regex` に一致すると `pass` になる場合があります。
今回、実際の診断を再確認すると、前者はIcarus 13.0の構文エラー、Verilator 5.052の
`Unsupported: interconnect` と構文エラーでした。後者のIcarus診断は
`Reference ports not supported yet` と関数の非input引数への拒否で、静的寿命のref禁止を
判定できる根拠にはなりません。Verilatorは後者を受理します。

これらはテストの違反刺激そのものの誤りではなく、ツール未対応による拒否と規格違反の検出を
ランナーの `pass` だけでは区別できない問題です。正常な同機能を受理できることも確認し、
意図した違反の診断内容を確認する必要があります。
両ファイルの `oracle` は `spec` のみであり、動作カバレッジ側では固定版の承認済み違法系
oracleとして扱わず、この偶然の `pass` を実行確認率に計上していません。
レビュー判断台帳にも登録保留の理由を残しました。

## M07: 判定対象を観測せずにPASSを表示するシナリオ

[test_edge_detection.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch9/test_edge_detection.sv) のTest5–7は、
sigの立上り・立下りとrst_nの変化を与えた後、固定のPASSを表示します。
監視しているイベントはclkだけで、sig/rst_nのイベント検出器や検出数の確認はありません。
この3シナリオの期待出力は、対象エッジをまったく処理しなくても一致します。
対象信号ごとの監視を用意し、各刺激での検出数と不検出も確認する必要があります。

[test_disable_stmt_edge_cases.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch9/test_disable_stmt_edge_cases.sv) の
`accum_block` も、ローカルのsumを確認せず、ブロック後に別のcountへ10を代入して
`[PASS] Disable with accum` を表示します。sumが55まで進んでもこの出力は変わりません。
sumの最終値を直接検査してください。他のpreserve_blockなど、値判定のあるシナリオは
集合証拠として対応付けています。

[test_task_disable_2.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch9/test_task_disable_2.sv) は、探索を途中で止めなくても
foundやrow/colが同じ値に残る入力を使っています。またconditional_processには
50しか渡さず、disableへ入る負値や100超の入力を実行しません。
途中停止後には変わらないはずのカウンタや重複した対象値、分岐へ入る入力が必要です。
このファイル内のreturnの観測をdisableの証拠には使っていません。

## M08: 遅延を実行しても、遅延時間や右辺の評価時点を検査していない

[test_timing_edge_cases.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch9/test_timing_edge_cases.sv) は、
`#(delay_val)` や `data = #5 8'hAA` の後で定数の代入結果を確認しますが、
対象遅延の前後の時刻や、待機中の別プロセスからの観測はありません。
この代入箇所の遅延を無視する誤実装でも、同じPASS出力になり得ます。
さらに右辺が定数なので、待機前の値を保存する規則も検査できません。

経過時間と更新前後の状態を検査し、右辺の保存を確認する場合は待機中に右辺を変える必要があります。
既存の[test_assign_delay_edge_cases.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch9/test_assign_delay_edge_cases.sv) は
経過時間を判定し、[test_intra_assignment_repeat_nonblocking.sv](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch9/test_intra_assignment_repeat_nonblocking.sv) は
右辺とrepeat回数を書き換えた後の更新値・時刻を観測するため、これらの有効な証拠を別途登録しました。
後者の負のrepeat一例を、0・x・zまで含む境界要求全体の証拠にはしていません。

## 登録の基準

生成テストは生成元の式・表と各出力ファイルを照合し、
実際の入力状態・観測位置・期待値が確認できた要求だけを登録しています。
真理値表の未出現セル、符号の違いが結果に現れないケース、
コンパイル成功だけでは確認できない型・幅・エラー条件は自動的に成功へ換算していません。
対応根拠、入力SHA-256、レビュー担当・日付は `coverage/behaviors.json` に保持します。
AIによる照合であり、独立した人による確認済みを意味しません。

モジュール・インターフェース・プログラムのヘッダーでのpackage importは、
3本のテストを `check_groups` としてまとめました。
部分的な成功を要求全体の成功にせず、同じ実行回で3本すべての成功を必要とします。
