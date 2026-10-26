# 附属書ヘッダ・VPIテストの追加と既存テストの照合（2026-10-23）

[現在の集計](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/behavior-coverage-summary.md) / [照合台帳](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/test-requirement-matching.md) / [累積の進捗・指摘](existing-test-matching-review-20261022.md) / [シミュレータと規格の差異](simulator-differences.md)

20%超過の後、50%を目標に作業を続け、途中で区切りました。
この記録は、そのうち独立した検証を終えた部分だけを台帳へ取り込んだ結果です。
検証が済んでいない新規テストと照合案は取り込んでいません。

## 集計

| 項目 | 前 | 後 |
| --- | ---: | ---: |
| 対応済み要求（暫定設計網羅率） | 2,465（20.009741%） | **3,889（31.569121%）** |
| 新鮮な成功証跡のある要求（暫定実行確認率） | 1,292（10.487864%） | **2,396（19.449631%）** |
| 本文（1〜40章、9,486行）の対応済み要求 | 2,430（25.62%） | 2,779（29.30%） |
| AND集合証拠のある要求 | 126 | 147 |
| 保留判断（テスト数・判断数） | 406本・546件 | 433本・578件 |
| テスト数 | 3,938 | 3,986 |
| 対応のあるテスト | 1,386 | 1,539 |

- 追加した対応根拠は1,465件、対応要求は1,424件増えました。
- **増分の大半は附属書のCヘッダです。** K.2とM.2では定数1個が1要求行として登録されており、定数だけで855行あります。
  暫定値はすべての登録行を同じ重みで数えるので、本文だけの値も併記しました。
- 確定値（設計・実行とも）は引き続き未確定です。分母の承認、意味上の重複整理、解釈保留が残っています。
- 担当はAI（Claude Opus 5.5）です。作成者とは別の検証用エージェントが誤りや検証漏れがないか確認しましたが、独立した人による確認ではありません。

## 内訳

### 1. 附属書のCヘッダを検証する新規テスト（24本、1,081要求）

| テスト | 内容 | 要求 |
| --- | --- | ---: |
| `ch36/test_vpi_user_h_*_constants`（5本） | vpi_user.h（K.2）の定数456個の値 | 456 |
| `ch36/test_sv_vpi_user_h_*_constants`（6本） | sv_vpi_user.h（M.2）の定数399個の値と、vpiCoverMax/vpiCoveredMaxの共有 | 400 |
| `ch36/test_vpi_user_h_routine_declarations` | K.2のルーチン宣言41個の型 | 41 |
| `ch36/test_vpi_user_h_type_declarations`、`test_vpi_user_h_type_guards` | PLI型、vpiHandle、構造体のフィールド型・順序・typedef名・共用体、ガード | 10 |
| `ch36/test_sv_vpi_user_h_declarations` | M.2の構造体、コールバック型、vpi_register_assertion_cb、ガード、vpi_user.hの読み込み | 5 |
| `ch35/test_svdpi_h_declarations`、`test_svdpi_h_after_vpi_user_h`、`test_svdpi_h_sv_mask` | svdpi.h（I.2/I.3、H.10.1.2）のルーチン宣言66個、型、マクロ、ガード、svDpiVersion | 78 |
| `ch36/test_vpi_compatibility_h_*`（6本） | vpi_compatibility.h（L.2）の版ごとの名前の対応付け、36.12.2.1の版選択、K.2の読み込み位置 | 91 |

確認方法:

- 定数の値は、規格本文の`#define`から求めて期待出力にしました。シミュレータの出力は使っていません。
  検証担当も、本文とPDFから3通りで値を独自に抽出して照合しています。
- 定数は`#ifdef`で囲んで出力するので、未定義なら行が欠けます。値は`enum`の初期化子に使うので、整数定数式でなければコンパイルが止まります。intの範囲外でもゼロ除算でコンパイルが止まります。
  検証担当は855定数のそれぞれについて8種類の変異（+1、浮動小数、±2^32、u接尾辞、文字列、空定義、未定義）を試しました。clang/gccとC/C++の計27,360ビルドのうち、期待出力と一致したものは0件です。
- 宣言は、C11の`_Generic`とC++の`decltype`で、規格の型と完全一致するかを評価されない式で比べます。このため、シミュレータが実装していないルーチンでもリンクは不要です。
  戻り値型、引数型、ポインタの段数、const、可変長引数の有無を1つずつ誤らせると、該当行が0になることを確認しました。
- 互換テストは、規格本文から復元したvpi_compatibility.hとvpi_user.hに対して、CとC++の両方で期待出力と一致することを確認しました。
- 検証は3回行いました。1回目は、`(int)`キャストで浮動小数の定義を区別できないとして定数が全件却下されました。2回目は、intの範囲外の値が切り詰められるとして再び全件却下されました。どちらもテストを直しています。
  ガードの働き、共用体であること、`SV_MASK`の式、インクルードの位置についても、指摘を受けてテストを直しています。
- 対応付けを見送った行は次のとおりです。いずれもヘッダの宣言だけでは観測できない条件を含みます。
  - 使い方の規則や値の意味を含む行：DELAY-FIELD、VALUE・ARRAYの各メンバー、STEP-STRUCT、TIME、VECTOR、STRENGTH、SYSTF、L.1 INCLUSION。
  - Windows専用の分岐を含むSIZE-TYPES。
  - `#if`でしか値を見ていないI.3 SCALARS（テストは修正済み、再検証は未実施）。
  - N=32のときの未定義動作がコンパイラに依存するI.3 UNSIGNED。
  - 観測できない条件を含むI.3 MASK。
- シミュレータの結果：
  - Verilator 5.052：17本がseed 1/73とも一致しました。
  - Icarus Verilog 13.0：ヘッダが一部の定数と宣言しか持たないため、どれも一致しません。
  - 互換テスト6本と`test_svdpi_h_sv_mask`は、どちらのシミュレータとも一致しないため`:oracle: spec`だけにしています。

### 2. 37章のVPIオブジェクトモデルの新規テスト（24本、193要求）

- instance・scope・block・net・port・ref objなどの関係図と詳細規則を、C helperで実際に辿って値を比較するテストです。
- 作成担当が26本を書き、別の検証担当が全テストと全照合案を確認しました。テスト24本が合格、照合案は195件が採用、36件が却下です。
  欠陥ありとされた2本（`test_vpi_io_decl_relations_props`、`test_vpi_nettype_net_select_kind`）は、期待値の一部が規格から導けないため取り込んでいません。
- 23本は`:oracle: spec`だけです。Icarus 13.0はヘッダに定数が足りずC helperをコンパイルできず、Verilator 5.052はVPIで登録したシステムタスクを呼べません。
  C helperは、1800-2023版の標準ヘッダに対してCでは警告なし、C++では文字列リテラルの変換警告だけでコンパイルできることを確認しました。
  `test_vpi_def_line_directive`はIcarus 13.0と一致します。

### 3. 既存テストの照合（150要求）

- 9区間（3.12.1〜6.3.1、6.16.1〜15.5.4、20.4.2〜21.3.1、24.3〜28.5、37.10〜37.16）の未対応要求を、引用している既存テストと照合しました。
- 照合担当1体と検証担当1体を組にして進め、照合案のうち166件が採用、91件が却下です。既存テストだけで対応した要求は150件です。
- 採用率が低い主な理由は次の3点です。
  - 要求の条件を刺激する既存テストがそもそも無い。
  - 型・符号・境界の片側しか観測していない。
  - 引用節が足りず、照合の対象外になる（引用を足せば対応できる例が多数あったが、テストの入力が変わり実行証跡が古くなるため、今回は見送った）。

## 追加した指摘と保留（M98–M129）

| 番号 | テスト | 区分 | 要点 |
| --- | --- | --- | --- |
| M98 | `ch11/test_real_operand_result_types` | 期待値 | real/shortrealはbit-stream typeではなく、20.6.2はその式の`$bits`を定めない。 |
| M99 | `ch37/test_vpi_nettype_declarations` | 引用 | 37.10の図が使うtag vpiNetTypedefが附属書Mに定義されていない。 |
| M100 | `ch20/test_pla_sync_snapshot_versus_async_update` | 期待値 | PLAの出力引数にnetを使っている。20.16は変数を要求する。 |
| M101 | `ch14/test_clocking_output_skew_cycle_delay` | 引用 | 即時と次サイクルのドライブを観測しているが、14.16を引用していない。 |
| M102 | `ch8/test_illegal_final_class_extended` | 期待値 | stderrの照合がファイル名と行番号だけで、`:final`未対応のエラーと区別できない。 |
| M103 | `ch8/test_super_new_default` | 部分観測 | 基底引数がすべてint・input・位置指定で、default展開の条件の一部しか見ていない。 |
| M104 | `ch8/test_class_typed_param` | 部分観測 | class型を型パラメータにした特殊化を構築・比較していない。 |
| M105 | `ch7/test_queue_edge_cases` | 部分観測 | 上限付きキューの上限を超える書込みを起こさない。 |
| M106 | `ch11/test_let_nested` | 複合要求 | 置換と括弧付けは観測するが、展開後の合法性検査には違法系が要る。 |
| M107 | `ch39/test_vpi_assertion_system_task_control` | 期待値 | 引数付き`$assertkill`のコールバックがTable 20-8と合わない。 |
| M108 | `ch20/test_assertcontrol` | 部分観測 | Unlockが何もしない実装でも同じ出力になる。 |
| M109 | `ch21/test_monitor_end_of_step` | 部分観測 | 再開時に必ず表示するかを区別できない。 |
| M110 | `ch11/test_shortreal_result_and_condition_types` | 期待値 | M98と同じく、shortreal/real式の`$bits`は規格が定めない。 |
| M111 | `ch4/test_reactive_region_set_order` | 期待値 | 期待する行順が、4.5の参照アルゴリズム（Re-NBAの更新をReactive領域で実行）と矛盾する。 |
| M112 | `ch4/test_pli_phase_chain_after_nba_and_end_write` | 期待値 | cbReadWriteSynchはPre-NBAでもPost-NBAでもよいのに、Post-NBAを前提にしている。 |
| M113 | `ch5/test_attrib_module` | 部分観測 | 属性の値を一度も読んでいない。 |
| M114 | `ch6/test_untyped_parameter_width_from_override` | 部分観測 | 実数での上書きとLSBが0の条件を観測していない。 |
| M115 | 同上 | 期待値 | 無サイズの1の幅を32に固定しているが、規格は32以上としか定めない。 |
| M116 | `ch6/test_dollar_parameter_unbounded` | 部分観測 | `[$:6]`に含まれる値を試していない。 |
| M117 | `ch6/test_illegal_automatic_variable_nonblocking` | 複合要求 | 自動変数の場合だけで、動的配列要素の場合がない。 |
| M118 | `ch6/test_illegal_dynamic_array_element_continuous` | 複合要求 | 動的配列要素の場合だけで、自動変数の場合がない。 |
| M119 | `ch10/test_comb_strength_multi` | 部分観測 | highz0を他の強度として扱う誤実装でも同じ結果になる。 |
| M120–M123 | `ch14/test_illegal_clocking_*`（コンパイル単位の外側、package、function、task） | 期待値 | `clk`が未宣言のため、期待する行のエラーが未宣言識別子の診断でも出る。 |
| M124 | `ch15/test_semaphore_edge` | 引用 | try_getの失敗を直接観測しているが、引用節が対応していない。 |
| M125 | `ch15/test_mailbox_typeless_try_type_check` | 引用 | 型なしmailboxの動的な型検査を観測しているが、引用節が対応していない。 |
| M126 | `ch14/test_clocking_input_with_expression` | 引用 | 1stepの直前値を観測しているが（M71の不足を補う）、引用節が対応していない。 |
| M127–M129 | `ch28/test_primitives_multi_input`、`test_gate_primitives`、`test_gate_primitives_2` | 期待値 | ゲートの出力端子に変数を接続している。28.3の文法ではnet_lvalueが必要。 |

区分の「期待値」は`oracle_issue`、「部分観測」は`partial_observation`、「複合要求」は`compound_requirement`、「引用」は`citation_refinement`です。
これらのテストの入力と期待値はこの作業では変更していません。

## 実行証跡

新規48本は、次の3つの実行回として別々に保存しました。全件の結果は上書きしていません。

- `coverage/results/header-vpi-tests-20261023-icarus13.json`：Icarus Verilog 13.0（v13_0-dirty）。1 pass、47 known。
- `coverage/results/header-vpi-tests-20261023-verilator-seed1.json`：Verilator 5.052（seed 1）。17 pass、31 known。
- `coverage/results/header-vpi-tests-20261023-verilator-seed73.json`：Verilator 5.052（seed 73）。17 pass、31 known。

`known`は成功に数えていません。照合で対応付けた既存テストは、保存済みの実行結果の入力ハッシュとランナーが現行版と一致するかを照合しています。

## 残っている作業

- 50%の目標には届いていません。
- 照合と新規テストの作成は残りの区間でも進めましたが、検証が済んでいない新規テストと照合案は取り込んでいません。後日、検証してから取り込む予定です。
- 対応付けを見送っている範囲：
  - 附属書B（予約語）と22.14.xの版別キーワードの行は正常系の要求で、予約は違法系テストでしか観測できないため対応付けられない。
  - 附属書F（アサーションの形式意味論）と34章（保護エンベロープ）は対象外とした。
