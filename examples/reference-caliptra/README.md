# Caliptraの暗号・鍵管理IPのDV環境の参照例

Root of Trustを構成する暗号・鍵管理IPを題材に、既知の期待値、UVMの予測器と比較器、zeroize・reset、機能カバレッジ、上位環境への再利用を読む例です。まずSHA-512の単体環境を入口にします。[公開DV環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版

[chipsalliance/caliptra-rtl / `bcd1a0c2dd897c2f378ad068c28a3452342111d2`](https://github.com/chipsalliance/caliptra-rtl/tree/bcd1a0c2dd897c2f378ad068c28a3452342111d2)を読みます。2026-11-03の読解用固定版です。実際の製品へ適用する場合は、RTL・ROM・firmwareの対応するリリースと、submoduleの版を確認します。

## 読む順序

| 順序 | ソース | 確認すること |
| --- | --- | --- |
| 1 | [READMEの実行手順](https://github.com/chipsalliance/caliptra-rtl/blob/bcd1a0c2dd897c2f378ad068c28a3452342111d2/README.md) | Verilator、単体TB、UVM単体・上位の経路と、それぞれの依存 |
| 2 | [SHA512_predictor.svh](https://github.com/chipsalliance/caliptra-rtl/blob/bcd1a0c2dd897c2f378ad068c28a3452342111d2/src/sha512/uvmf_sha512/uvmf_template_output/verification_ip/environment_packages/SHA512_env_pkg/src/SHA512_predictor.svh)、[期待ベクトル](https://github.com/chipsalliance/caliptra-rtl/tree/bcd1a0c2dd897c2f378ad068c28a3452342111d2/src/sha512/tb/vectors) | SHAモード・試験番号から期待値を読む処理、ファイル・長さ・選択条件 |
| 3 | [SHA512_environment.svh](https://github.com/chipsalliance/caliptra-rtl/blob/bcd1a0c2dd897c2f378ad068c28a3452342111d2/src/sha512/uvmf_sha512/uvmf_template_output/verification_ip/environment_packages/SHA512_env_pkg/src/SHA512_environment.svh) | 入力モニター→predictor→期待値ポートと、出力モニター→実測値ポートの接続 |
| 4 | [sha512_ctrl_cov_if.sv](https://github.com/chipsalliance/caliptra-rtl/blob/bcd1a0c2dd897c2f378ad068c28a3452342111d2/src/sha512/coverage/sha512_ctrl_cov_if.sv) | mode・init・next・ready・zeroize等のcoverpoint・crossと、ビルド時の有効化 |

生成されたpredictorの雛形コメントだけを見て、実装の有無を判断しません。この版には期待ファイルを選び、期待値トランザクションを生成・送信する処理があります。`SHA512_environment`は期待値と実測値を`uvmf_in_order_scoreboard`へ接続します。比較順序、残件、期待ファイルの欠落、モードと試験番号の範囲を、試験の完了条件まで追ってください。

## セキュリティIPとして読むポイント

| 観点 | 検証項目へ展開する問い |
| --- | --- |
| 暗号の値 | モード・メッセージ長・複数ブロック・byte順が期待ベクトルと一致するか |
| 秘密状態の消去 | 処理中のzeroize・resetに対し、内部状態、結果の有効性、次の要求受付をいつ確認するか |
| 状態と競合 | init／nextとready、zeroizeと処理中状態の組合せをどう刺激し、何を比較するか |
| 上位との接続 | 鍵・PCR等の経路、アクセス許可、エラー通知、firmwareの操作がどの観測点へ届くか |

表は仕様から検証項目を作るための問いで、固定版が全項目を証明済みという一覧ではありません。ハッシュ値の一致だけでは、鍵の機密性、アクセス制御、故障注入耐性、サイドチャネル対策まで確認したことにはなりません。[仕様からの項目展開](../../docs/method/spec-to-test-items-walkthrough.md)と[クロス条件の選定](../../docs/method/cross-test-selection-walkthrough.md)へ対応付けて読みます。

## ツール・ライセンス・確認範囲

固定版の上流手順は、UVM 1.1d・UVM Frameworks、QVIPのAHBモデル、Avery AXI VIP等を案内しています。公開リポジトリだけで、商用VIPを含む全依存が得られるわけではありません。Verilatorによる別経路もありますが、当該covergroupのファイルは`ifndef VERILATOR`で囲まれており、その経路の成功を同じ機能カバレッジの計測実績にはできません。

今回確認したのは固定ソース・期待値経路・TLM接続・カバレッジ・実行条件です。暗号IPやSoCのRTL実行、フルUVM、ベクトルの全件検算、セキュリティ評価・認証は未実施です。[LICENSE](https://github.com/chipsalliance/caliptra-rtl/blob/bcd1a0c2dd897c2f378ad068c28a3452342111d2/LICENSE)と各ファイル・外部依存の条件を保持します。上流コードはGit管理下へ複製せず、統合nightlyへ加算しません。
