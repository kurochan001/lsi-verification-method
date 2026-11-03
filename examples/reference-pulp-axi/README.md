# PULP AXIのランダム刺激・比較環境の参照例

AXI4／AXI4-Liteの接続IPを、UVMを使わないSystemVerilogの検証クラスとモニターで検証する例です。クロスバー、ID・データ幅変換、複数の未完了要求、チャネルごとの待ちを学べます。[公開DV環境の比較](../../docs/method/open-source-dv-environments.md)から、既存のVIPや小規模な実行例と比較できます。

## 参照する版

[pulp-platform/axi / `d436bd4936ba1c49cd87521df54580c5159114d3`](https://github.com/pulp-platform/axi/tree/d436bd4936ba1c49cd87521df54580c5159114d3)を読みます。これは2026-11-03に取得した読解用の固定版で、全構成の動作確認済みという意味ではありません。

## 読む順序

| 順序 | ソース | 確認すること |
| --- | --- | --- |
| 1 | [README](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/README.md)、[Bender.yml](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/Bender.yml) | DUTの役割、AXI4＋ATOPsの適用範囲、依存とビルド対象 |
| 2 | [src/axi_test.sv](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/src/axi_test.sv) | driver、ランダムmaster／slave、モニター、メモリーモデルを持つscoreboardの責務 |
| 3 | [test/tb_axi_xbar.sv](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/test/tb_axi_xbar.sv)、[tb_axi_xbar_pkg.sv](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/test/tb_axi_xbar_pkg.sv) | 複数ポート・ID・アドレス領域、要求と応答の追跡、比較と終了時の集計 |
| 4 | [scripts/run_vsim.sh](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/scripts/run_vsim.sh)、[.gitlab-ci.yml](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/.gitlab-ci.yml) | 構成とseedの列挙、分割実行、ログ、合否の採用条件 |

### 比較器を置くだけで終わらせない

`axi_scoreboard`のコンストラクターは`check_en`を0で初期化します。必要なチェックを`enable_all_checks()`等で有効にし、バスのreset解除後に`monitor()`を1回呼んで監視を開始します。このモデルの`reset()`もチェックを無効へ戻すため、再利用時は未完了要求がない条件と、必要なチェックの再有効化を確認します。クロスバーのTBは別クラスの`axi_xbar_monitor.run()`を使います。両者のAPIと、実際に接続される比較器を区別してください。

汎用`axi_scoreboard`の固定版はINCR burstまたは単一beatを前提とし、ATOP付き書込みを未対応として警告します。IP群全体のAXI4＋ATOPs対応を、このモデルの比較範囲へそのまま当てはめません。また、未初期化アドレスの読出しは未知値を期待値として許容するため、値の正しさを確認する試験ではメモリーの初期状態と書込みを定義します。

クロスバーでは、入力ポートの要求がどの出力へ向かい、応答のIDが元の要求へ戻るかを追います。`print_result()`は失敗件数に加え、実施件数0もエラーにします。再利用時は、期待件数と実施件数の一致、残ったキュー、警告・エラー・時間切れも完了条件へ含めます。

## 読解演習

1. master 2個・slave 2個のアドレスマップを紙に描き、同じIDを使う要求をどの範囲で区別するか整理する。
2. AW・W・B・AR・Rの待ちを別々に与える設定と、最大未完了数を探す。
3. 「出力先の取り違え」「応答IDの誤り」「最後の応答が返らない」の観測点と終了条件を記入する。
4. 構成・seedの全組合せ、CIの分割先、今回実行した組合せを対応付ける。

ランダムslaveのデータは、任意のアドレスに対する独立した期待値とは限りません。接続・順序の検査と、書込み後の読出し値を照合する検査で、使用するモデルと合格条件を分けてください。[ランダム探索の管理](../../docs/method/random-search-management.md)も参照できます。

## ツール・ライセンス・確認範囲

固定版の回帰スクリプトはQuestaの`vsim`を使います。Benderと、`common_cells`・`common_verification`・`tech_cells_generic`等の解決結果も記録します。[scripts/run_verilator.sh](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/scripts/run_verilator.sh)は`--lint-only`の経路で、このスクリプトの成功をランダムTBの実行成功へ読み替えません。

今回確認したのは固定版のソース・比較経路・設定です。上流TBのビルド・シミュレーション、機能カバレッジの収束は未確認です。主な配布条件は[SHL-0.51](https://github.com/pulp-platform/axi/blob/d436bd4936ba1c49cd87521df54580c5159114d3/LICENSE)で、取得する依存と各ファイルの表示も保持します。上流コードはGit管理下へ複製せず、参照例の件数を統合nightlyへ加算しません。
