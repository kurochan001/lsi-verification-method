# CV32系とCORE-V-VERIFの参照例

CV32は単一のCPU名ではなく、CV32E40P・CV32E40X・CV32E40Sなどを含む系列です。ここではCV32E40PのCORE-V-VERIFを入口に、コア別の計画・環境・参照モデル・実行条件を読む例を収録します。[外部DV環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版と対象

| 対象 | DVリポジトリと固定コミット | 読む入口 |
| --- | --- | --- |
| CV32E40P | [core-v-verif / `33917ee5db9ede3779cc658a5004d672320f164c`](https://github.com/openhwfoundation/core-v-verif/tree/33917ee5db9ede3779cc658a5004d672320f164c) | `cv32e40p_v1.8.3`タグ。`cv32e40p/`と共通`mk/` |
| CV32E40X | [cv32e40x-dv / `93ce70f1ae2ab2e66716e0c5648d27e67e161c2f`](https://github.com/openhwfoundation/cv32e40x-dv/tree/93ce70f1ae2ab2e66716e0c5648d27e67e161c2f) | コア専用の`env/`・`sim/`・`mk/` |
| CV32E40S | [cv32e40s-dv / `8b27b963ef08badfa350b4207a45e2c2cadb3001`](https://github.com/openhwfoundation/cv32e40s-dv/tree/8b27b963ef08badfa350b4207a45e2c2cadb3001) | コア専用の`env/`・`sim/` |

CORE-V-VERIFのデフォルトブランチだけで全コアの現在の配置を推測せず、対象コアとDV側の版を対で選びます。ここで取得したのはDV側の固定版で、各CPUのRTL・ISS・全外部依存を導入した結果ではありません。

## CV32E40Pで1件から追う

| 読む順序 | 固定版のファイル | 確認すること |
| --- | --- | --- |
| テストとソフトウェア | [hello-world/test.yaml](https://github.com/openhwfoundation/core-v-verif/blob/33917ee5db9ede3779cc658a5004d672320f164c/cv32e40p/tests/programs/custom/hello-world/test.yaml) | 選ぶプログラム、構成、起動条件。表示だけで比較・終了が成立したと判断しない |
| RTL等の版 | [ExternalRepos.mk](https://github.com/openhwfoundation/core-v-verif/blob/33917ee5db9ede3779cc658a5004d672320f164c/cv32e40p/sim/ExternalRepos.mk) | `CV_CORE_TAG`等と、生成器・ツール側の依存を区別する |
| 環境の責務 | [uvme_cv32e40p_env.sv](https://github.com/openhwfoundation/core-v-verif/blob/33917ee5db9ede3779cc658a5004d672320f164c/cv32e40p/env/uvme/uvme_cv32e40p_env.sv) | clock/reset、OBIメモリー応答、IRQ、debug、設定に応じた接続 |
| 命令・状態の比較 | [uvmt_cv32e40p_tb.sv](https://github.com/openhwfoundation/core-v-verif/blob/33917ee5db9ede3779cc658a5004d672320f164c/cv32e40p/tb/uvmt/uvmt_cv32e40p_tb.sv) | `USE_ISS`、RVFIからRVVIへの接続、比較に渡すCSR・例外等 |
| シミュレーターとISS | [vsim.mk](https://github.com/openhwfoundation/core-v-verif/blob/33917ee5db9ede3779cc658a5004d672320f164c/mk/uvmt/vsim.mk) | `USE_ISS`時の`USE_IMPERASDV`、ライブラリー、コンパイル時と実行時の指定 |

UVM環境のscoreboarding設定だけで、命令比較全体が有効だと判断しません。TBトップ・参照モデル・Makefileまで追います。ISSを外してプログラムが完走しても、ISSとの比較を確認した実行とは分けます。

CV32E40Xは[uvme_cv32e40x_env.sv](https://github.com/openhwfoundation/cv32e40x-dv/blob/93ce70f1ae2ab2e66716e0c5648d27e67e161c2f/env/uvme/uvme_cv32e40x_env.sv)、CV32E40Sは[uvme_cv32e40s_env.sv](https://github.com/openhwfoundation/cv32e40s-dv/blob/8b27b963ef08badfa350b4207a45e2c2cadb3001/env/uvme/uvme_cv32e40s_env.sv)を入口に、コア固有の要求・拡張・セキュリティ機構・割り込み・デバッグの条件を確認します。Pの合格をXやSへ一般化しません。

## 実行条件と確認範囲

UVM対応シミュレーター、対象コアのRISC-Vツールチェーン、生成器、選んだISS等が必要です。固定版には商用シミュレーターやImperasDVへ接続する経路があり、公開コードだけから実行時の全依存が無償・オープンソースとは判断できません。[PicoRV32の小演習](../reference-picorv32/README.md)とは実行条件が異なります。

この参照例では固定版の取得、上記の設定・ソース・接続を確認しました。フルUVM、CPUのRTL／ISS実行、フォーマル再証明、カバレッジ収束は未実行です。統合nightlyの登録数へ加算しません。

取得したLICENSE・ファイルごとのSPDX・外部依存の表示を保持してください。[Ibex DV](../reference-ibex-dv/README.md)と比較する際も、同じRISC-Vという理由でISSや設定を交換せず、ISA・CSR・IRQ・debugと比較粒度を対応付けます。
