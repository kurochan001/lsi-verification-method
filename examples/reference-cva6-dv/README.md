# CVA6のDV環境の参照例

CVA6の構成と実行経路、UVM環境、RVFIによる比較の接続を読む例です。[全体の比較](../../docs/method/open-source-dv-environments.md)と[Ibex DV](../reference-ibex-dv/README.md)を併せて参照してください。ここは**読解用の参照例**で、統合nightlyにCVA6を追加するランナーではありません。

## 参照する版

- 現在のリポジトリURL：[openhwfoundation/cva6](https://github.com/openhwfoundation/cva6)。旧`openhwgroup/cva6`からの移転を確認しています。
- 固定コミット：[`742dc82a0c706e0a3bfb98b709fd3ee06d50d12a`](https://github.com/openhwfoundation/cva6/tree/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a)
- 入口：[root README](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/README.md)、[verif README](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/README.md)

この版のroot READMEはmasterのread-only化とmainへの移行を案内しています。本資料では取得を確認できたmasterのSHAを読解対象に固定し、移行先や最新版を実行確認した結果とは扱いません。

## 実行経路を最初に分ける

| 経路 | 読む対象 | 区別する点 |
| --- | --- | --- |
| Verilator／Spike | [cva6.yaml](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/sim/cva6.yaml)、[cva6.py](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/sim/cva6.py) | `veri-testharness`と`spike`、プログラム・トレース、比較モード |
| 命令の生成 | [cva6-simulator.yaml](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/sim/cva6-simulator.yaml) | 生成器側のSVシミュレーター設定。CPUのRTLを動かすツール設定と同一視しない |
| UVMの環境 | [uvme_cva6_env.sv](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/env/uvme/uvme_cva6_env.sv)、[環境の説明](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/docs/UVM_verif_env.md) | agent、参照モデル、スコアボード、coverageの生成と接続 |
| 構成別の起動 | [smoke-tests-cv32a65x.sh](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/regress/smoke-tests-cv32a65x.sh) | 対象構成、ツールの導入、環境変数、実行するプログラムを読む |

固定版にはVerilator／Spikeを選ぶ経路があります。ただし、これを選ぶだけで、SVによる命令生成・すべてのUVM機能・商用形式のカバレッジ計画まで同時に実行できるとは扱いません。指向性プログラム、命令生成、RTL／ISS、カバレッジの各経路を特定します。

root READMEの汎用的な`smoke-tests.sh`という記述だけをコピーせず、固定版に存在する構成別スクリプトと内容を確認します。スクリプトには導入・ビルド・clean処理も含まれます。本資料では、これらを実行していません。

## UVMの設定と接続を追う

1. `uvme_cva6_env_c`から、clock/reset、AXI、core control、RVFI、ISA coverage、interrupt、CV-X-IFのagentを探す。
2. `create_env_components()`で、どの設定により参照モデル・スコアボードが生成されるか確認する。
3. `connect_scoreboard()`で、`tandem_enabled`時のRVFIと参照モデルの経路を追う。
4. `scoreboard_enabled`など、名前の異なる有効化条件を区別し、今回の比較・収集が有効か確認する。
5. XLEN・ISA・特権・CSR・退役ポート数と、参照モデル・比較順序をそろえる。

クラスが宣言されているだけでは、比較が有効であると判断しません。ドキュメントの図に加え、確認版の実コードの条件と接続を追います。

## 依存と確認範囲

[install-spike.sh](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/verif/regress/install-spike.sh)は、既定でCORE-V側のvendor化されたSpikeを参照します。[.gitmodules](https://github.com/openhwfoundation/cva6/blob/742dc82a0c706e0a3bfb98b709fd3ee06d50d12a/.gitmodules)とsubmoduleの版も記録してください。Ibex向けSpikeの導入結果だけで、CVA6のモデル条件がそろったとは判断しません。

この参照例では固定SHAの取得と、上記のソース・設定を確認しました。submoduleを含む全依存の導入、RTL／ISSの実行、フルUVM、カバレッジ測定は未実行です。

CVA6のroot LICENSEにはSolderpadの記載があり、参照するSV・スクリプト・文書にも個別のSPDXがあります。上流の条件を保持し、単一のApache-2.0や本リポジトリのLLVM例外にまとめて置き換えません。

[小規模RISC-V](../local-riscv-iss/README.md)、[UVMの上位再利用](../local-uvm-hierarchy/README.md)、[複数未完了と順不同](../local-uvm-outstanding/README.md)から進むと、構成・接続・順序・比較の有効化を具体的に確認できます。
