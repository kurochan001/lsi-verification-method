# 未登録テストの照合：第1回（2026-10-25）

[現在のカバレッジ](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/behavior-coverage-summary.md) / [全テストの照合台帳](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/docs/test-requirement-matching.md) / [照合の方法](requirements-to-tests-method.md) / [前回までの指摘](existing-test-matching-review-20261022.md)

この文書は、対応登録のない既存テスト2,514本を対象に始めた照合の、最初の区間の記録です。
テストの刺激と期待出力をIEEE 1800-2023の本文に照らし、独立した検証担当の反証を経て、
合格した対応だけを台帳へ取り込みました。

- 新たに対応登録したテスト：45本（未登録2,514本 → 2,498本）。内訳は、刺激が足りず保留にしていた要求のために新しく書いた6本と、シミュレータ側のCTestスイートから取り込んだ23本です。
- 新たに対応した要求：99行（7,341行 → 7,440行）。
- 暫定設計網羅率：59.590876% → **60.394513%**（7,440/12,319）。65%まで残り568行です。
- 暫定実行確認率：33.566036%（4,135/12,319）のまま。シミュレータは再実行していません。
- 対応を保留した判断：490本・1,061ペア（`citation_refinement` 33、`compound_requirement` 109、`oracle_issue` 49、`partial_observation` 530）。

登録済み本数は、少なくとも一つの要求との対応がある本数です。
16本すべての観測を精査し終えたという意味ではなく、全テストの意味上の照合は未完了です。

## 方法

[照合キット](../../tools/matching_kit/README.md)の`propose.py`で候補を読み、`add`・`hold`で提案し、
別の担当が`verdict`で反証し、`merge.py`が合格分だけを台帳へ適用しました。
提案・判定・作業メモはリポジトリ外（`/tmp/opencode/matching/`）に置き、リポジトリ内は
`merge.py`と生成ツールだけが更新しています。

登録の基準は[方法文書](requirements-to-tests-method.md)の6章のとおりです。

- 刺激が要求の**全条件**を起こすこと。
- 期待出力が、その要求にだけ反する実装を区別できること。
- 名前・説明・引用節・API呼び出しの事実だけを根拠にしないこと。
- 非NULLだけの確認、常に同じ値でも通る検査、自己比較、個数だけの確認、
  規格が順序を決めない観測に依存しないこと。
- 違法系の要求には`:should_fail_because:`と`:expected_stderr_regex:`を持つテストだけを使うこと。

迷った場合は登録せず、範囲を限定した保留として記録しました。
保留はテスト全体の承認ではなく、その要求との対応を保留した記録です。

## 登録した対応

章ごとの内訳です。要求IDは`coverage/behaviors.json`の行に対応します。

| 章 | テスト | 要求 |
|---|---|---|
| 5.6.3 | [test_vpi_systf_names](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch36/test_vpi_systf_names.sv) | `PLI-SYSTEM-EXTENSION`、`SYSTEM-NAME-CHARACTERS`、`SYSTEM-PREFIX` |
| 11.4.6 | [test_gen_xz_wne_03](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/gen/ch11/test_gen_xz_wne_03.sv) | `UNMASKED-UNKNOWN` |
| 11.5.3 | [test_static_prefix_disjoint_field_drivers](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch11/test_static_prefix_disjoint_field_drivers.sv) | `LONGEST-STATIC-PREFIX` |
| 13.6 | [test_dpi_import_calls_exported_value](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch13/test_dpi_import_calls_exported_value.sv) | `DPI-SUBROUTINES` |
| 16.5 | [test_assertion_clocked_by_named_event](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch16/test_assertion_clocked_by_named_event.sv) | `CLOCK-TICK` |
| 16.14.6.4 | [test_procedural_concurrent_assertions](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch16/test_procedural_concurrent_assertions.sv) | `DISABLE-PROCESS` |
| 18.5.10 | [test_static_constraint_mode](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch18/test_static_constraint_mode.sv) | `STATIC-BLOCK`、`STATIC-MODE-SHARED` |
| 19.8.1 | [test_cg_sample_from_contexts](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch19/test_cg_sample_from_contexts.sv) | `CUSTOM-SAMPLE-CONTEXT` |
| 19.11.3 | [test_cg_merge_auto_and_transition_names](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch19/test_cg_merge_auto_and_transition_names.sv) | `SCALAR-BIN-IDENTITY`、`TRANSITION-IDENTITY`、`AUTO-BIN-IDENTITY` |
| 21.2.1.6 | [test_pattern_format_enum_string_null](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch21/test_pattern_format_enum_string_null.sv) | `PATTERN-STRING`、`PATTERN-HANDLES` |
| 21.3.7 | [test_file_fflush_ferror](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch21/test_file_fflush_ferror.sv) | `FERROR-CLEAR` |
| 23.2.1 | [test_module_header_styles](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch23/test_module_header_styles.sv) | `HEADER-STYLES` |
| 23.3.3.7.1 | [test_interconnect_port_merge](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch23/test_interconnect_port_merge.sv) | `INTERCONNECT-MERGE` |
| 36.3 | [test_vpi_systf_names](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch36/test_vpi_systf_names.sv) | `NAME-CASE` |
| 38.10 | [test_vpi_gate_delays](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch38/test_vpi_gate_delays.sv) | `DELAY-LAYOUT-0-0` |
| 38.32 | [test_vpi_gate_delays](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch38/test_vpi_gate_delays.sv) | `PUT-LAYOUT-0-0` |
| 38.35 | [test_vpi_put_value_array](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch38/test_vpi_put_value_array.sv) | `ONE-VALUE` |
| 6.18 / 8.27 | [test_typedef_declaration_forms](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch6/test_typedef_declaration_forms.sv) | `CLASS-FORWARD-OMISSION` |
| A.2.1.3 | [test_typedef_declaration_forms](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch6/test_typedef_declaration_forms.sv) | `TYPEDEF`、`FORWARD-TYPES` |

上記16本に、次の2節の新規29本を加えた45本が今回の登録です。
主な観測は次のとおりです。

- **36.3 / 5.6.3**：大文字小文字だけが違う2名、名前に`$`を含む名、数字を含む名、
  最後の1文字だけが違う72文字の2名をPLIで登録し、6名がそれぞれの登録名で実行されること。
  名前の大小区別・任意長・全文字有意と、PLIによる追加のシステムタスクを同時に観測します。
- **19.11.3**：`merge_instances`で単一ビン（`one_t` 100.00）、遷移配列（`t` 50.00）、
  自動ビン（33.33 → 66.67）が名前で重なることを、被覆率の数値から確認します。
- **19.8.1**：引数付きに上書きした`sample`が、automatic関数（1/8）、forkした2プロセス（3/8）、
  sequenceのmatch item（4/8）からデータを受け取ること。sequenceの値がPreponedの
  `d`（2と6）であり、NBA後の`d`（6と7）なら5/8になることを区別します。
- **38.10 / 38.32**：`mtm_flag=FALSE`・`pulsere_flag=FALSE`で`da[0]`が1番目、
  `da[1]`が2番目の遅延になること。読み出しの`3 5`と、設定後の立ち上がり17・立ち下がり39で
  順序の入れ替えを区別します。
- **6.18 / 8.27 / A.2.1.3**：`typedef Fwd;`が後続の`class Fwd;`に解決すること、
  typedefの3代替と4種のunpacked次元、5種の前方型キーワードを、`deep_t=32`・`w5_t=5`・
  `p=3,4/2`などの値で確認します。
- **18.5.10**：`static constraint`の宣言と、constraint_modeが全オブジェクトで共有されること。
  通常制約`c_d`が共有されない対照も同じ出力に含みます。

## 刺激の追記で解消した保留（新規テスト6本）

既存テストの刺激が要求の全条件に届かず保留にしていた13要求について、新しいテスト6本を追加しました。
期待値は規格本文から先に導き、Icarus Verilog 13.0（一部は Verilator 5.052 も）で一致を確認しています。

| 要求 | 新規テスト | 追加した刺激 | `:oracle:` |
|---|---|---|---|
| 5.6.1 `ESCAPE-CHARACTER-DOMAIN` | [test_escaped_identifier_character_domain](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch5/test_escaped_identifier_character_domain.sv) | 印刷可能ASCII 33〜126の各文字、標準例の複数文字名、エスケープしたキーワード`\net` | iverilog + verilator |
| 5.7.1 `FILL-CONTEXT` | [test_unsized_fill_all_values](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch5/test_unsized_fill_all_values.sv) | `'0`/`'1`/`'x`/`'z` × 8/33/65ビット、自己決定幅の`$bits('1)` | iverilog |
| 5.8 `TIME-NUMERIC-FORM` | [test_time_literal_units_and_fraction](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch5/test_time_literal_units_and_fraction.sv) | `fs/ps/ns/us/ms/s`の6単位と固定小数点`3.5ns` | iverilog + verilator |
| 11.4.6 `RIGHT-ONLY-WILDCARD` | [test_wildcard_lhs_unknown](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch11/test_wildcard_lhs_unknown.sv) | LHSのx/z（非ワイルド）、RHSの`?`/x/zがLHSの0/1/x/zに一致、既知不一致による0確定 | iverilog |
| 20.7 `DIMENSION-NUMBERING`、`PREDEFINED-INTEGER-DIMENSION`、`DIMENSIONS`、`UNPACKED-DIMENSIONS` | [test_array_query_functions](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch20/test_array_query_functions.sv) | 4次元配列の次元番号、typedef展開、整数型の単一packed次元、packed/unpacked/動的/string/realの次元数 | verilator |
| 20.7 `ARRAY-QUERY-SYNTAX`、`CONSTANT-ARRAY-QUERY`、`INCREMENT`、`RIGHT-BOUND`、`INVALID-DIMENSION` | [test_array_query_types_and_invalid](https://github.com/kurochan001/kirimasim-tests/blob/0da4f2fc/tests/ch20/test_array_query_types_and_invalid.sv) | 型引数、定数式、空キュー/動的配列の-1、無効次元の全x | spec |

- **5.6.1**：Icarus 13.0は1文字名`\#`を特別な名前として誤解析するため、`#`は`\a#b`の内部で刺激しています。他の93文字は単独名で宣言し、文字コードを連結表示して1文字ずつ解決を確認します。
- **5.7.1**：既存テストは`'0`/`'1`だけだったため、`'x`/`'z`と33/65ビットの文脈、自己決定幅1を追加しました。
- **5.8**：単位`ns`の整数だけだったため、6単位すべてと固定小数点部を追加しました。
- **11.4.6**：最初の検証では「RHSのワイルドカードがLHSの既知0と向き合う行がない」と指摘され、`0000 ==? ????`など4行を追加して再検証を受けました。LHSのx/zが非ワイルドであること、RHSのワイルドカードが0/1/x/zのすべてに一致すること、既知不一致が0を確定することを分けて観測します。
- **20.7**：配列クエリは、Icarus 13.0が型引数と定数式を受理せず、空キューの`$right`/`$increment`に0を返し、`int dyn[]`を0次元と数えるため、実行可能な4要求と仕様専用の5要求に分けました。実行可能側はVerilator 5.052で一致し、Icarusは動的配列の次元数だけ異なります。
- 6本とも`lint_metadata.py`を通し、`runsim.py`で`:oracle:`の記載どおりの結果を確認しました。Verilatorは2状態なので`'x`/`'z`のテストと、4状態のRHSを定数以外に持つワイルドカード比較は実行できません。

## シミュレータ側の CTest スイートからの取り込み（23本）

`../kirimasim` の `tests/suite` には、同じメタデータ形式（`:lrm:`、`:oracle:`、`:expected_stdout:`）を持つ SystemVerilog テストが2,818本あります。
既存スイートとはファイル名・内容の重複がなく、そのまま取り込める形式です。ただし次の制約があります。

- 2,125本は `:expected_stderr:`（警告・エラー文字列の完全一致）を持ち、このスイートの `:expected_stderr_regex:` 形式ではないため、そのままでは取り込めません。
- 57本の違法系は `:expected_stderr_regex:` がありません。
- 61本は `:args:` にシミュレータ固有のオプションを持ちます。
- 26本は最初の引用節が附属書Aで、ディレクトリ規約（`chNN`）に合いません。
- `:tags:` は `proc` や `sched` などの分類なので `chNN` へ書き換え、`:generator:` はこのリポジトリに生成器がないため外し、ファイル名には `test_` を付けます。

このうち540本を一括で取り込み、要求優先で照合しました。未対応要求の候補は641行あり、**すべてリンクできれば65.13%** に届く計算でした。
実際に登録できたのは21本・58行で、残りは部分観測・複合要求・診断未検査として保留しました。登録に至らなかった519本は、未登録テストを増やさないため取り下げました（元の kirimasim 側に残っています）。

| 章 | 取り込んで登録したテストの例 | 主な要求 |
|---|---|---|
| 21 | test_display_radix_forms、test_display_finish、test_time_format_matrix、test_empty_argument_matrix | 書式、%%、%t、空引数 |
| 21 | test_file_close_fd、test_file_output_initial | ファイル記述子、fdisplay |
| 23 | test_net_port_merge_kinds、test_instance_arrays | Table 23-1 のポート崩壊、インスタンス配列 |
| 9 | test_edge_matrix、test_delay_value_matrix | エッジ表9-2、x/z 遅延 |
| 10 | test_delay_matrix、test_procedural_continuous_assign、test_net_strengths_wire | ベクタ遅延、force、強度 |
| 6/12/20/22/28 | test_package_call_matrix、test_cond_truth、test_time_query_matrix、test_unconnected_drive_none_module、test_gate_containers | 連続代入、if の真理値、時刻問い合わせ、未接続ポート、ゲート配列 |

- 取り込んだテストは `tests/imported/chNN/` に置き、既存章のディレクトリ内容（入力ダイジェスト）を変えないようにしています。
- 期待値は元の suite のものをそのまま使わず、各バッチで規格本文から再導出し、独立検証を受けました。
- `test_always_star` は `always @*` 本体の自己読みで規格上も非収束になるため却下しました。
- `test_instance_arrays` と `test_net_port_merge_kinds` は `:oracle:` が実際のシミュレータ結果と一致しません。期待値は規格どおりなのでリンクは成立しますが、`:oracle:` の修正候補です。

### 65% への見通し

- 現在60.39%。65%には残り568行が必要です。
- 取り込み候補の上限は65.13%で、残る候補をすべて完全観測できた場合のぎりぎりです。実際の登録率は約24%なので、この pool だけでは62%前後が現実的な到達点です。
- 65%に届かせるには、`:expected_stderr:` を持つ2,125本の警告系テストの正規化、または未対応要求（約4,900行）への新規テスト作成が必要です。

## 却下した対応案

検証担当が反証し、登録しなかった案です。却下は将来の再提案を禁じません。

| 要求 | テスト | 却下の理由（要旨） |
|---|---|---|
| 5.6.1 `ESCAPE-CHARACTER-DOMAIN` | test_escaped_identifier_with_dot | `.`1文字だけを刺激し、エスケープ識別子の文字領域全体を観測しない |
| 5.7.1 `FILL-CONTEXT` | test_unsized_fill_wide_part_select_nba | `'0`/`'1`だけで、`'x`/`'z`の全ビット充填を刺激しない |
| 5.8 `TIME-NUMERIC-FORM` | test_time_literal_scaled_to_unit | 整数と`ns`だけで、他の単位と固定小数点部を刺激しない |
| 11.4.6 `RIGHT-ONLY-WILDCARD` | test_gen_xz_weq_01 | LHSの`z`が既知RHSビットと向き合う行がなく、`z`をワイルドカード扱いする実装を区別できない |
| 11.4.10 `SHIFT-SIGN-CONTEXT` | test_gen_width_ashr_01 | signed左オペランドの片方向だけで、unsigned左オペランドのゼロ充填を区別できない |
| 16.12.17 `NO-NEGATION-STRONG` | test_illegal_recursive_property_negated | 6演算子のうち`not`だけを刺激し、残り5つの拒否を観測しない |
| 16.16 `MULTICLOCK-LEADING` | test_illegal_multiclock_two_leading_clocks | default leading clockの継承（許可節）を刺激せず、義務節だけの観測 |
| 19.6.1.4 `CROSS-SET-EXPRESSION` | test_cg_cross_set_expression | 配列リテラル受理とビン選択だけで、非リテラル式とcast要件を観測しない |
| 19.11.3 `AUTO-CROSS-IDENTITY` | test_cg_merge_auto_and_transition_names | マージ無効のインスタンス加重平均でも同じ8.33/16.67になり、和集合を区別できない |
| 21.2.1.6 `PATTERN-ENUM` | test_pattern_format_enum_string_null | 有効値の名前表示だけで、無効値の基底型表示を刺激しない |
| 23.2.1 `MODULE-HEADER-FIELDS` | test_module_header_styles | 既定ライフタイムとポート型を期待出力が反証せず、`(8 bits)`は親変数の幅 |
| 39.4.1 `SYSTEM-ENABLE-FAIL-TEXT` | test_vpi_assertion_system_control | 同時刻のシステムコールバック順に依存する疑い |
| 39.4.1 `SYSTEM-DISABLE-FAIL-TEXT` | test_vpi_assertion_system_control | 同上 |
| 39.5.1 `CONTROL-VPIASSERTIONSYSEND` | test_vpi_assertion_sys_end_discards_and_blocks | SysEnd後の破棄・新規停止・後続制御を1本で観測したという主張を確認できない |
| 40.3.2.1 `RETURN-SV-COV-CHECK-SV-COV-NOCOV` | test_coverage_uninstantiated_module | 常にNOCOVを返す実装でも通り、OK/PARTIALとの対比がない |

## 保留の傾向

1,061ペアの保留を、次の4種類に分けています。

- `partial_observation`：要求の複数条件の一部だけを刺激している。
  例：`$bits`の幅だけを出してbit-stream castをしない、VPIの保護フラグがfalse側だけ、
  シフトのsigned側だけ、制約の`get`だけを刺激する。
- `compound_requirement`：1行に独立した複数条件が束ねられている。
  例：`16.12.17`の6演算子、`19.11.3`の複数のビン同一性、`23.2.1`のヘッダ7項目。
  要求を条件ごとに分割するか、複数テストのAND集合が必要です。
- `oracle_issue`：期待値が実装の選択に依存する、または規格が順序・時刻を一意に決めない。
  例：`cbReadWriteSynch`のPre/Post-NBA、同時刻のコールバック順、VPIハンドル解放後の値。
- `citation_refinement`：テストの`:lrm:`が参照する節と、実際に呼ぶAPIの節が違う。
  例：`38.16`（配列取得）を引用して`vpi_get`だけを呼ぶ、`38.31`（put_data）を引用して
  `vpi_release_handle`だけを呼ぶ。

保留は`propose.py`が自動で除外するため、同じテスト・要求の組を再提案するときは、
先に保留理由を解消する必要があります。

## 残りと次の候補

- テスト総数は6,038本（今回の新規29本を含む）。未登録は2,498本で、このうち候補要求が全くないテストが約380本あり、
  要求台帳側の分割・観測可能化が必要です。
- 未対応要求4,952行のうち、未登録テストが候補になるのは約1,970行です。
  残りは候補テスト自体がなく、新規テストの対象です。
- 197本は、いずれかの未対応要求の**唯一の候補テスト**です。
  1本で複数要求を満たせるものは限られますが、優先して確認する価値があります。
- 次の区間の候補：`ch6`の型変換、`ch38`のVPI配列・ハンドル、`ch20`の`$bits`、
  `ch23`の非ANSIポート、`ch19`のカバレッジ残り。
- 生成テスト（`tests/gen/`）は、同じ要求を複数テストが観測できるため、
  最も完全な1本だけを登録し、残りは保留にしています。

## 再現

```sh
python3 tools/matching_kit/partition.py /tmp/opencode/matching/assign
python3 tools/matching_kit/propose.py scope /tmp/opencode/matching/assign/p01-*.json
python3 tools/matching_kit/propose.py test tests/chN/test_x.sv
python3 tools/matching_kit/propose.py req SV2023-...
python3 tools/matching_kit/merge.py /tmp/opencode/matching/proposals/wave2 \
  --reviewer 'DeepSeek V4.1 Flash (AI); not an independent human review' --date 2026-10-25
python3 tools/behavior_coverage.py --update
python3 tools/requirement_matching.py --update
python3 tools/behavior_coverage.py --check --require-source-reviewed
python3 tools/requirement_matching.py --check
python3 -m unittest discover -s tools -p 'test_*.py'
```

## 注意

- 照合と検証はAIが行ったもので、人による独立レビューではありません。
  台帳の`reviewer`欄にもその旨を記録しています。
- 今回、テスト本体・期待値・要求定義・保存済み実行結果は変更していません。
  期待値は規格本文から導き、シミュレータの出力を期待値に写していません。
- シミュレータを再実行していないため、新しい26要求には新鮮な成功証跡がありません。
  設計対応だけを登録し、実行確認率は増やしていません。
- `:oracle: spec`のテスト（ch19のカバレッジ、ch23のinterconnect、ch36のVPIシステムタスクなど）は、
  Icarus 13.0とVerilator 5.052のどちらも一致しないため、実行による裏付けはありません。
