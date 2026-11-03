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

## ツール・ライセンス・確認範囲

この版のVerilator経路はC++コンパイラー、Perl、make、構成に対応した生成済みRTL等を使います。Makefileには`nv_full`や出力先の固定的な前提があるため、現在のツールへそのまま適用できるとは保証しません。Cモデルを使う経路の依存も別に確認します。

今回確認したのは固定ソース、トレース、比較・終了の経路です。RTL・Cモデルの構築、推論、フルDV、機能カバレッジの収束は未実行です。[NVIDIA Open NVDLA License and Agreement v1.0](https://github.com/nvdla/hw/blob/8e06b1b9d85aab65b40d43d08eec5ea4681ff715/LICENSE)と個別ファイルの条件を保持し、本リポジトリのライセンスへ置き換えません。上流ソースはGit管理へ複製せず、統合nightlyへ加算しません。

手元で動かす基礎題材は[AI用回路](../README.md#ai用回路)と[C++参照モデル](../local-cpp-reference/README.md)を参照してください。
