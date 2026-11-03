# Ibex DVの参照例

IbexのSV/UVM検証環境を、刺激・モニター・ISS比較・計画の順で読む例です。[外部環境の比較と読み方](../../docs/method/open-source-dv-environments.md)から進めます。ここは**上流コードの読解例**で、本リポジトリのnightlyでIbexのフルDVを実行するランナーではありません。

## 参照する版

- リポジトリ：[lowRISC/ibex](https://github.com/lowRISC/ibex)
- 固定コミット：[`f4515520c0045bb8ef1e72d46ed82499a6ac5f18`](https://github.com/lowRISC/ibex/tree/f4515520c0045bb8ef1e72d46ed82499a6ac5f18)
- 入口：[core_ibex README](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/dv/uvm/core_ibex/README.md)、[検証の説明](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/doc/03_reference/verification.rst)

## 1件のテストから環境を追う

| 読む順序 | 固定版のファイル | 確認すること |
| --- | --- | --- |
| 1. テストの選択 | [testlist.yaml](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/dv/uvm/core_ibex/riscv_dv_extension/testlist.yaml) | `riscv_arithmetic_basic_test`、生成オプション、反復数、生成側とRTL側のテスト名 |
| 2. 環境の構成 | [core_ibex_env.sv](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/dv/uvm/core_ibex/env/core_ibex_env.sv) | 命令・データ応答、IRQ、cosim、スコアボードの生成と接続 |
| 3. 命令の観測と比較 | [ibex_cosim_scoreboard.sv](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/dv/uvm/core_ibex/common/ibex_cosim_agent/ibex_cosim_scoreboard.sv) | RVFIのFIFO、Spikeの初期化、退役命令のDPI呼出し、リセット時の処理 |
| 4. モデルとの境界 | [spike_cosim_dpi.cc](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/dv/uvm/core_ibex/common/ibex_cosim_agent/spike_cosim_dpi.cc) | C++／SVの境界、モデルへの設定、比較結果の返し方 |
| 5. ツールと構成 | [rtl_simulation.yaml](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/dv/uvm/core_ibex/yaml/rtl_simulation.yaml)、[ibex_configs.yaml](https://github.com/lowRISC/ibex/blob/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/ibex_configs.yaml) | 選んだ構成、シミュレーター、DPI・カバレッジの設定 |

まず算術の最小テストで、RISCV-DVの生成と、生成済みプログラムを実行するIbex RTLを分けます。その後、IRQ・debug・メモリーエラーなどを、単純な命令ログの比較からどのように扱い広げているかを追います。

命令・データメモリーのエージェントは、CPUが出す要求へ応答する側です。CPUの動作を指示する命令列と、外部応答のタイミングや異常の刺激は、それぞれの責務で読みます。

## 実行する場合の条件

固定版のクイックスタートはXcelium、参照資料はVCSについて記載しており、シミュレーター設定には両経路があります。実行には、選択したUVM対応シミュレーターとライセンス、RISC-Vツールチェーン、lowRISCの`ibex_cosim` Spike forkなどを確認します。

上流READMEにある形を、対象テスト名で示すと次のようになります。これは**今回実行していないフルDVのコマンド例**で、`dv/uvm/core_ibex/`内と上流の準備手順を前提にします。

```text
make --keep-going IBEX_CONFIG=opentitan SIMULATOR=xlm ISS=spike ITERATIONS=1 SEED=1 TEST=riscv_arithmetic_basic_test WAVES=0 COV=0
```

`COV=0`での実行成功はカバレッジ収束を意味しません。一般のSpikeをそのまま使う前に、fork、ISA・CSR・NMIの扱い、ビルド条件をそろえます。

Verilatorを使う[簡易システムの経路](https://github.com/lowRISC/ibex/tree/f4515520c0045bb8ef1e72d46ed82499a6ac5f18/examples/simple_system)もありますが、ここで読むcore DVと同じ確認範囲にはなりません。本資料では、いずれのRTLシミュレーションも実行していません。

## 小規模教材との対応

[小規模RISC-V](../local-riscv-iss/README.md)で結果・例外の比較を、[C++参照モデル](../local-cpp-reference/README.md)でモデルとタイミング検査の分離を確認してから読むと、ISSを追加しても残るインターフェース・リセット・終了条件の役割を追いやすくなります。

取得した固定版のソースとファイルパスは確認しています。上流のLICENSE・各ファイルの表示を保持し、ソースを本リポジトリのライセンスへ読み替えません。
