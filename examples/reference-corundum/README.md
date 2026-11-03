# CorundumのNIC・PCIe・DMA検証環境の参照例

FPGA NICの小さなパケット処理ブロックから、PCIe・DMA・キュー・Ethernetを接続した環境へ進む例です。Python／cocotbの刺激・参照計算・受信比較と、複数構成の回帰を読みます。[公開DV環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版

[corundum/corundum / `1ca0151b97af85aa5dd306d74b6bcec65904d2ce`](https://github.com/corundum/corundum/tree/1ca0151b97af85aa5dd306d74b6bcec65904d2ce)を読みます。2026-11-03に取得した固定版で、ここでは上流のテストを実行していません。

## 小さなブロックから読む

| 段階 | ソース | 学ぶこと |
| --- | --- | --- |
| パケットの期待値 | [rx_hash/test_rx_hash.py](https://github.com/corundum/corundum/blob/1ca0151b97af85aa5dd306d74b6bcec65904d2ce/fpga/common/tb/rx_hash/test_rx_hash.py) | Scapyで作るフレーム、PythonのToeplitz hash計算、RTL出力のhash値・種別との比較 |
| 刺激と構成 | 同じテストの`TestFactory`とpytestパラメーター | Ethernet／IP／UDP／TCP、入力の待ち、データ幅64／256 bitの組合せ |
| NICの結合 | [test_mqnic_core_pcie_us.py](https://github.com/corundum/corundum/blob/1ca0151b97af85aa5dd306d74b6bcec65904d2ce/fpga/common/tb/mqnic_core_pcie_us/test_mqnic_core_pcie_us.py)、[mqnic.py](https://github.com/corundum/corundum/blob/1ca0151b97af85aa5dd306d74b6bcec65904d2ce/fpga/common/tb/mqnic.py) | PCIe側のモデル・ドライバー操作からDMA・送受信・完了・キュー選択へ至る経路 |
| 再現と分割 | [tox.ini](https://github.com/corundum/corundum/blob/1ca0151b97af85aa5dd306d74b6bcec65904d2ce/tox.ini)、[Regression Tests](https://github.com/corundum/corundum/blob/1ca0151b97af85aa5dd306d74b6bcec65904d2ce/.github/workflows/regression-tests.yml) | 固定パッケージ、pytestの構成名、10グループへの分割、実行結果の対応 |

`rx_hash`では、同じフレームからソフトウェアで期待hashを計算し、出力値と種別をそれぞれ比較します。NIC全体では、送ったペイロードの一致だけでなく、受信キューやチェックサム等も別の観測点になります。各assertがどの試験区間で有効か、無効化された比較がないかをコードから追います。

## 読解演習

1. `rx_hash`で1つのUDPフレームを選び、フレーム生成→入力→期待hash→出力比較を線で結ぶ。
2. 入力の休止と下流のバックプレッシャーを区別し、当該インターフェースが受け付ける停止条件を確認する。
3. NIC側で、パケットの値・順序、descriptorとcompletion、DMA領域、キュー番号を対応付ける。
4. 小さなブロックのデータ幅行列と、NIC全体の構成行列を別々に書き出す。1構成の成功から全行列の成功を推定しない。

出発点は[ネットワークの検証手順](../../docs/method/network-verification.md)と[小規模ネットワークSoC](../local-network-soc/README.md)です。ソフトウェアのドライバーモデルによる試験と、実機のLinuxドライバー・PCIeハードIP・物理リンクの評価も分けて記録します。

## ツール・ライセンス・確認範囲

固定版のCIはPython 3.10とIcarusを使い、`tox.ini`はcocotb 1.7.2、cocotb-test 0.2.4、AXI・Ethernet・PCIeの拡張モデル等を指定しています。本リポジトリの現行cocotb環境と同じ条件ではありません。新しいPythonやcocotbへ置き換える場合は、API・依存の互換性を別途確認します。上流Pythonのassertによる検査を保持するため、最適化による無効化にも注意します。

今回確認したのは固定版のソース・比較・構成・CI条件です。RTLのシミュレーション、FPGAビルド、実機通信、カバレッジ収束は未確認です。[LICENSE](https://github.com/corundum/corundum/blob/1ca0151b97af85aa5dd306d74b6bcec65904d2ce/LICENSE)、ファイルごとのBSD等の表示、外部モデル・ドライバーの条件を保持してください。上流コードはGit管理下へ複製せず、統合nightlyにも登録しません。
