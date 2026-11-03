# NVDLAの演算トレース・メモリー比較環境の参照例

深層学習の推論アクセラレーターを、入力データ・重み・レジスター操作・割り込み待ち・出力メモリー比較へ分けて読む例です。演算結果の数値形式と、データを転送して処理を完了させる制御の両方を追います。[公開DV環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版と世代

[nvdla/hw / `8e06b1b9d85aab65b40d43d08eec5ea4681ff715`](https://github.com/nvdla/hw/tree/8e06b1b9d85aab65b40d43d08eec5ea4681ff715)の`nvdlav1`を読みます。[README](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/README.md)は、このブランチを構成固定のNVDLA 1.0と説明しています。別世代の構成可能なRTLや、v2のUVM手順を、この版の導入手順として混在させません。

## 読む順序

| 順序 | ソース | 確認すること |
| --- | --- | --- |
| 1 | [conv_8x8_fc_int16/input.txn](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/verif/traces/traceplayer/conv_8x8_fc_int16/input.txn) | 入力・重みのload、レジスターのwrite／read、割り込み待ち、出力のdumpと期待ファイル |
| 2 | [input_txn_to_verilator.pl](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/verif/verilator/input_txn_to_verilator.pl) | テキスト操作からバイナリトレースへの変換と、データファイルの扱い |
| 3 | [verif/verilator/nvdla.cpp](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/verif/verilator/nvdla.cpp) | CSBの設定・読出し比較、AXIのメモリー応答、トレースの実行、出力byteの比較 |
| 4 | [verif/verilator/Makefile](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/verif/verilator/Makefile)、[cmod/](https://github.com/nvdla/hw/tree/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/cmod) | Verilatorのビルド条件、RTLの生成物、別に存在するCモデルの責務 |

VerilatorのC++ハーネスはバス応答・トレース再生・結果比較を担当します。C++で書かれていることを理由に、演算を独立に計算するCモデルと同一視しません。掲載トレースでは期待出力ファイルを使うため、その生成元・数値形式・丸め・飽和・配置の根拠も追跡対象です。

## 読解演習

`conv_8x8_fc_int16`を選び、次を検証項目表にします。

| 項目 | 刺激・観測 | 合格条件として整理すること |
| --- | --- | --- |
| 入力の準備 | 入力・重みのファイルと転送先 | 要素の型、byte数、アドレス、配置・strideが演算設定と一致 |
| 設定 | CSBのwrite／readとmask | 比較対象bitと予約bitを区別し、読戻し値が一致 |
| 完了 | `wait`と割り込み状態・clear | 対象処理の完了と、clear後の状態を時間上限付きで確認 |
| 演算結果 | `dump_mem`と期待ファイル | 対象領域の値・範囲が一致し、入力や重みの領域を破壊しない |

`nvdla.cpp`は出力不一致とCSB読出し不一致を別の終了コードで返します。一方、割り込み待ちのループにも着目し、回帰へ採用する場合は外側の時間上限・強制終了・未完了の扱いを用意します。「トレースを読み終えた」「結果が一致した」「期限内に完了した」を個別に確認する練習になります。

## 出力ファイル処理の不具合と修正例

固定版の`TraceLoader::axievent()`は、`creat()`の戻り値を`if (!fd)`で判定しています。有効なファイル記述子0で比較を飛ばす一方、失敗を表す負値を見逃します。さらに`write()`・`close()`の戻り値を検査せず、出力ファイルの保存失敗を合否へ反映しません。標準入力を閉じた子プロセスで、期待値と異なるデータでも比較せず`test_passed`が1になることを再現しました。

次は**この固定版に対する修正差分**です。原版を保持し、`nvdla.cpp`の別コピーと差分を保存した`nvdla-dump-io.patch`を同じディレクトリに置き、`patch -p0 < nvdla-dump-io.patch`で適用できます。元の著作権表示とLICENSEを保持します。ファイル作成・1 byte書込み・closeの失敗を不合格にし、記述子0でもデータ比較を実施します。上流への送付・反映は行っていません。

```diff
--- nvdla.cpp
+++ nvdla.cpp
@@ -610 +610,2 @@
-			if (!fd) {
+			if (fd < 0) {
+				_test_passed = 0;
@@ -616 +617,6 @@
-				write(fd, &da, 1);
+				if (write(fd, &da, 1) != 1) {
+					fprintf(stderr, "AXI: FAIL: could not write one output byte\n");
+					matched = 0;
+					_test_passed = 0;
+					break;
+				}
@@ -626 +632,5 @@
-			close(fd);
+			if (close(fd) < 0) {
+				perror("close(dumpmem)");
+				matched = 0;
+				_test_passed = 0;
+			}
```

原版と修正版のメソッドを抽出し、バス応答を代替するC++の単体環境で、正常・データ不一致・記述子0の正常／不一致・作成失敗・書込み失敗・0 byte書込み・close失敗の8条件を確認しました。記述子0のケースでは実際のファイルを使い、I/O失敗は戻り値を注入しています。原版は6条件で期待する判定や比較回数と異なり、修正版は全8条件が成功しました。これはファイルI/Oと限定した比較分岐の確認で、NVDLAのRTL・演算・全トレースの検証ではありません。[レビュー記録](../../PROVENANCE.md#noncpu-review-20261103)も参照してください。

## ツール・ライセンス・確認範囲

この版のVerilator経路はC++コンパイラー、Perl、make、構成に対応した生成済みRTL等を使います。Makefileには`nv_full`や出力先の固定的な前提があるため、現在のツールへそのまま適用できるとは保証しません。Cモデルを使う経路の依存も別に確認します。

今回確認したのは固定ソース、トレース、比較・終了の経路と、上記のI/O修正に対するC++単体8条件です。RTL・演算Cモデルの構築、推論、フルDV、機能カバレッジの収束は未実行です。[NVIDIA Open NVDLA License and Agreement v1.0](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/LICENSE)と個別ファイルの条件を保持し、本リポジトリのライセンスへ置き換えません。上流ソース全体はGit管理へ複製せず、統合nightlyへ加算しません。

手元で動かす基礎題材は[AI用回路](../README.md#ai用回路)と[C++参照モデル](../local-cpp-reference/README.md)を参照してください。
