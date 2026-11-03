# HPDcacheのSystemC・UVM環境の参照例

CPUに接続する前のキャッシュ単体で、要求・メモリー応答・期待状態・順序・待ちを追う例です。HPDcacheのRTL側にあるSystemC環境と、別のUVM環境を読み分けます。[外部DVの比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版

| 対象 | リポジトリと固定コミット |
| --- | --- |
| RTLとSystemC TB | [cv-hpdcache / `9b065ccb7c61c37c0bc36b7bed7eab653bff00b8`](https://github.com/openhwfoundation/cv-hpdcache/tree/9b065ccb7c61c37c0bc36b7bed7eab653bff00b8) |
| UVM環境 | [cv-hpdcache-verif / `f46150dd0b68f300255c8dddcec73e0c2c4f961e`](https://github.com/openhwfoundation/cv-hpdcache-verif/tree/f46150dd0b68f300255c8dddcec73e0c2c4f961e) |

2件は読解する固定版で、相互の互換性を確認した組ではありません。UVM側が指定するsubmodule・設定を実際のDUTの版として記録します。

## 2つの入口

| 経路 | 読むファイル | 実行時の条件・確認すること |
| --- | --- | --- |
| SystemCの単体TB | [rtl/tb/README.md](https://github.com/openhwfoundation/cv-hpdcache/blob/9b065ccb7c61c37c0bc36b7bed7eab653bff00b8/rtl/tb/README.md)、[Makefile](https://github.com/openhwfoundation/cv-hpdcache/blob/9b065ccb7c61c37c0bc36b7bed7eab653bff00b8/rtl/tb/Makefile) | Verilator 5.018以上、SystemC 2.3.4以上に加え**SCV 2.0.1以上**、Perl等。CPUを接続しない要求生成・メモリー応答の環境 |
| 単体の刺激・比較 | [hpdcache_test_random_seq.h](https://github.com/openhwfoundation/cv-hpdcache/blob/9b065ccb7c61c37c0bc36b7bed7eab653bff00b8/rtl/tb/sequence_lib/hpdcache_test_random_seq.h)、[hpdcache_test_scoreboard.h](https://github.com/openhwfoundation/cv-hpdcache/blob/9b065ccb7c61c37c0bc36b7bed7eab653bff00b8/rtl/tb/include/hpdcache_test_scoreboard.h) | 生成要求と実完了、メモリーモデル・期待状態、ランダム化と終了条件 |
| UVMの構成 | [README.md](https://github.com/openhwfoundation/cv-hpdcache-verif/blob/f46150dd0b68f300255c8dddcec73e0c2c4f961e/README.md)、[hpdcache_env.svh](https://github.com/openhwfoundation/cv-hpdcache-verif/blob/f46150dd0b68f300255c8dddcec73e0c2c4f961e/testbench/env/hpdcache_env.svh) | キャッシュ・prefetcher、複数の刺激と共通部品。上流案内はQuesta等を使う |
| UVMの比較・実行計画 | [hpdcache_sb.svh](https://github.com/openhwfoundation/cv-hpdcache-verif/blob/f46150dd0b68f300255c8dddcec73e0c2c4f961e/testbench/env/hpdcache_sb.svh)、[nightly list](https://github.com/openhwfoundation/cv-hpdcache-verif/blob/f46150dd0b68f300255c8dddcec73e0c2c4f961e/testbench/simu/hpdcache_nightly_test_list) | load/store・AMO・LR/SC・待ち・置換等のテストと、比較器・構成の対応 |

SystemC側の実行形は次のとおりです。**今回未実行のコマンド例**で、依存と環境変数を準備した`rtl/tb/`内を前提にします。

```text
make build -j2
make run SEQUENCE=random LOG_LEVEL=1 NTRANSACTIONS=10000 SEED=42
```

本リポジトリの`full`環境はSystemCを含みますが、SCVやHPDcacheの全依存を準備するものではありません。[SoCLib](../local-vci-soclib/README.md)が動いたことだけで、このTBの導入済みとは判断しません。

## 比較するシナリオ

同じアドレスへのstore後のloadを出発点に、部分書込み、同じsetへの競合、dirty lineの追い出し、miss中の追加要求、バックプレッシャー、メモリー応答の順序、AMO・LR/SC、reset・flush等を、採用構成と仕様へ対応付けます。MSHR等の未完了情報、受付・完了・取消の対応と、外部メモリー側への書込みも追います。単体の成功をCPU接続後の一貫性や全SoCの保証へ一般化しません。

固定版UVM READMEは、CFG1での条件付きの動作、SV PLRUモデルの無効化、未検証のAXI5 adapter等を明記しています。テスト名やファイルの存在だけで全構成・機能が確認済みとはしません。最新版の状況を、固定版の記述から推測することも避けます。

今回確認したのは固定ソース・構成・経路で、両TBのビルド・実行・カバレッジ収束は未確認です。RTL側のSolderpad、UVM側・外部依存のLICENSEと個別表示を保持してください。
