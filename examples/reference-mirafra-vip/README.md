# Mirafra mBitsのAPB・AXI4 VIPの参照例

Mirafraの[mBits](https://mirafra.com/opensource/mbits/)が公開するバスVIPを読み、刺激・BFM・モニター・比較をどのように再利用するかを学びます。ここではAPBとAXI4の2件を固定版で参照します。[環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版

| VIP | リポジトリと固定コミット |
| --- | --- |
| APB | [apb_avip / `b9e0f885b85d7425d665fe544afa2f75b07a728d`](https://github.com/mbits-mirafra/apb_avip/tree/b9e0f885b85d7425d665fe544afa2f75b07a728d) |
| AXI4 | [axi4_avip / `86b46171c534dfa5521ecfe9329184d7b0d72898`](https://github.com/mbits-mirafra/axi4_avip/tree/86b46171c534dfa5521ecfe9329184d7b0d72898) |

Mirafraという単一のDUTを検証する例ではなく、公開VIPの読み方の例です。HDL側のBFMとHVL側のUVMクラスを分ける構造を、加速の実測値とは別に確認します。

## APBからAXI4へ読む

| 入口 | 固定版のファイル | 確認すること |
| --- | --- | --- |
| APBの最小試験 | [apb_regression.list](https://github.com/mbits-mirafra/apb_avip/blob/b9e0f885b85d7425d665fe544afa2f75b07a728d/src/hvl_top/testlists/apb_regression.list) | `apb_32b_write_test`等の実クラス名。拡張子や重複した`.list`を付けない |
| APBの駆動・比較 | [apb_master_driver_bfm.sv](https://github.com/mbits-mirafra/apb_avip/blob/b9e0f885b85d7425d665fe544afa2f75b07a728d/src/hdl_top/master_agent_bfm/apb_master_driver_bfm.sv)、[apb_scoreboard.sv](https://github.com/mbits-mirafra/apb_avip/blob/b9e0f885b85d7425d665fe544afa2f75b07a728d/src/hvl_top/env/apb_scoreboard.sv) | phase、待ち・エラー、モニターの観測と期待値の根拠 |
| AXI4のモード | [README.md](https://github.com/mbits-mirafra/axi4_avip/blob/86b46171c534dfa5521ecfe9329184d7b0d72898/README.md)、[makefile](https://github.com/mbits-mirafra/axi4_avip/blob/86b46171c534dfa5521ecfe9329184d7b0d72898/sim/questasim/makefile) | `MODE=b2b`・`slave`・`master`。何をDUTとし、どちらのagentが能動か |
| AXI4の比較 | [axi4_scoreboard.sv](https://github.com/mbits-mirafra/axi4_avip/blob/86b46171c534dfa5521ecfe9329184d7b0d72898/src/hvl_top/env/axi4_scoreboard.sv)、[回帰リスト](https://github.com/mbits-mirafra/axi4_avip/blob/86b46171c534dfa5521ecfe9329184d7b0d72898/src/hvl_top/testlists/axi4_back_to_back_regression.list) | AW／W／B・AR／R、ID・複数未完了・順不同、メモリーとデータ比較、終了時の残件 |

固定版AXI4の`b2b`は、active masterとactive slaveのVIP同士を接続する経路です。通信の整合を調べられても、対象製品のRTLや、互いと独立した期待値を検証した実行とは区別します。`slave`／`master`でDUTへ接続するときは、製品のレジスター・メモリー・副作用の仕様を独立にモデル化し、プロトコル検査と機能比較を対応付けます。

`MODE`はコンパイル対象のパッケージを切り替え、固定版の手順はコンパイル用ファイルリストの選択も変更します。コミットだけでなく、選んだモード・実際のファイルリスト・変更差分も保存します。

## 実行条件と適用時の点検

上流の[APB README](https://github.com/mbits-mirafra/apb_avip/blob/b9e0f885b85d7425d665fe544afa2f75b07a728d/README.md)にはQuesta・Xcelium、ソース内には他の商用向け設定もあります。AXI4の案内はQuesta向けMakefileを使います。公開されたSV/UVMのソースと、シミュレーター・カバレッジ・加速器等の実行条件を分けます。

この参照例では固定版の取得とソース・テストリスト・設定を確認しました。フルUVM、Verilatorでのビルド・実行、エミュレーション、プロトコル全体への適合性・速度は未確認です。[ローカルのAPB](../local-apb/README.md)・[AXI4](../local-axi4/README.md)で学んだ待ち・順序・比較の要求を、VIPの機能表・設定・チェッカーへ対応付けてください。

採用する構成では、意図した不正転送・比較不一致・タイムアウト・結果欠落を検出できるかも確認します。VIPの警告を一括抑止したり、同じエラーを両端が出さないことだけで合格にしたりしません。取得版のMIT LICENSE・著作権表示を保持します。
