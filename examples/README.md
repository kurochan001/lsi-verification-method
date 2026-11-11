# 検証例一覧

回路・検証方式ごとに、対象範囲と主な検証内容、必要なツールをまとめています。個別の実行手順・合格条件・証跡は各例のREADMEを参照してください。

検証の考え方は[検証手法の案内](../README.md#検証の進め方)、共通の準備と実行は[ルートREADME](../README.md#準備と実行)から確認できます。

用語は[用語集](../docs/glossary.md)、ツールの準備・lintの合否・失敗解析・AI提案・上位UVM・結果の採用で迷う点は[FAQ](../docs/faq.md)を参照してください。例数、構成数、親の判定、子のJUnit件数、要求数は、それぞれ別の集計です。

- [バス・レジスタ・アドレス](#バスレジスタアドレス)
- [FIFO・通信・仲裁](#fifo通信仲裁)
- [割り込み・タイマー・周辺機能の結合](#割り込みタイマー周辺機能の結合)
- [DMA・メモリ・順序制御](#dmaメモリ順序制御)
- [CDC・クロック・リセット・低電力](#cdcクロックリセット低電力)
- [演算・故障注入・保護・性能・DFT](#演算故障注入保護性能dft)
- [AI用回路](#ai用回路)
- [ネットワーク・パケット処理](#ネットワークパケット処理)
- [航空宇宙・高信頼システム](#航空宇宙高信頼システム)
- [ロボティクス・モーション制御](#ロボティクスモーション制御)
- [オートモーティブ](#オートモーティブ)
- [アナログ・デジタル協調](#アナログデジタル協調)
- [画像処理](#画像処理)
- [プロセッサ](#プロセッサ)
- [静的タイミング解析](#静的タイミング解析)
- [フォーマル検証・等価性・反例再現](#フォーマル検証等価性反例再現)
- [SVA・UVM・仕様生成・ソフトウェア連携・検証効率](#svauvm仕様生成ソフトウェア連携検証効率)
- [外部のオープンソースDV環境（参照例）](#外部のオープンソースdv環境参照例)

「主なツール」はPythonに加えて必要な環境です。IcarusはIcarus Verilog、フォーマルはYosys・SymbiYosys（SBY）・Z3、UVMはVerilator・C++20環境・外部のAccellera UVMを指します。Verilatorでビルド・実行する例にはC++コンパイラとmakeも必要です。lintだけの例では不要です。詳細な版・追加パッケージ・セットアップは各手順を参照してください。

## バス・レジスタ・アドレス

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [APBレジスタ](local-apb/README.md) | 読出し・書込み、待ち状態、エラー、W1Cとイベントの競合 | Icarus |
| [AHB-Lite](local-ahb/README.md) | アドレス／データのパイプライン、バイトレーン、2サイクルERROR、ランダム転送 | Icarus |
| [AXI4-Lite](local-axi/README.md) | AW／Wの独立受付、WSTRB、応答保持、読書き競合、ランダム転送 | Icarus |
| [AXI4のバースト・ID](local-axi4/README.md) | INCRバースト、複数未完了転送、ID、RLAST、4KiB境界 | Icarus |
| [AHB／AXI-Lite→APB](local-bus-bridge/README.md) | 応答変換、レジスタ・タイマーへの接続、IRQ、リセット | Icarus |
| [AXI4-Liteの幅変換](local-width-converter/README.md) | 64→32ビット、部分書込み、応答集約、途中リセット | Icarus |
| [アドレスマップ](local-address-map/README.md) | RAM・タイマー・GPIOのデコード、別名、未割当、バイトストローブ、IRQ集約 | Icarus |
| [AHB／AXIの方式別検査](local-bus-validation/README.md) | プロトコルチェッカー、SVA、クロス、X・リセット、性能、lint・コードカバレッジ | Icarus＋Verilator |
| [VCIとSoCLibのCABA RAM](local-vci-soclib/README.md) | 32／64ビット、部分書込み、パケット、待ち中保持、ID、エラー、途中リセット、原版の不具合再現 | C++17＋SystemC 2.3.4 |

## FIFO・通信・仲裁

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [同期FIFOのランダム検証](local-fifo/README.md) | 参照キュー、空／満杯、同時要求、データ順序、深さ・幅の構成変更 | Icarus |
| [ready/validのランダム検証](local-stream/README.md) | バックプレッシャー、valid・データ保持、欠落・重複・順序、排出 | Icarus |
| [ラウンドロビン・アービタ](local-arbiter/README.md) | 排他制御、待ち中の選択保持、受理順序、条件付きの公平性 | Icarus |
| [UARTのランダム検証](local-uart/README.md) | 8N1／8E1／8O1、独立した送受信照合、エラー、偽スタート、リセット復帰 | Icarus |
| [SPIのランダム検証](local-spi/README.md) | CPOL／CPHAの4モード、独立した送受信タイミング、busy中のstart要求 | Icarus |
| [I²Cのランダム検証](local-i2c/README.md) | ACK／NACK、Repeated START、クロックストレッチ、途中リセット | Icarus |
| [AXI4-Stream](local-axis/README.md) | パケット境界、TKEEP・TLAST、データ順序、途中パケットの破棄 | Icarus |
| [パケットスイッチ](local-packet-switch/README.md) | 2×2の経路選択・パケット単位の仲裁、先頭提示時の占有、入力の空白と出力待ち、末尾での解放 | Icarus |
| [CRC・ACK・再送リンク](local-retry-link/README.md) | フレーム／ACKの消失・破損、再送と重複排除、配送結果が確定しない再送上限、待ち・両端リセット | Icarus |
| [クレジット方式のフロー制御](local-credit-link/README.md) | 2仮想チャネルの受付・送信・クレジット返却、保持、リセット | Icarus |

## 割り込み・タイマー・周辺機能の結合

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [割り込み・CDCと継続的リグレッション](local-irq-cdc/README.md) | イベント保持、W1C、リセット、CDC遅延モデル、要求とカバレッジの判定 | Icarus |
| [APB＋割り込み](local-apb-irq/README.md) | マスク中の保持、W1Cクリアとイベント再発生、マスク更新の競合、機能間クロス | Icarus |
| [APB＋UART＋割り込み](local-apb-uart/README.md) | レジスタ操作から実際の送受信・エラー検出・IRQ通知までの結合、同時操作の競合 | Icarus |
| [タイマー・ウォッチドッグ](local-timer-watchdog/README.md) | 単発・周期・停止、kick・IRQクリアと満了の競合、同時満了 | Icarus |
| [APB＋タイマー＋ウォッチドッグ](local-apb-timer/README.md) | バス完了と満了・kick・clearの競合、IRQマスク、リセット要求 | Icarus |
| [優先度付き割り込み](local-priority-irq/README.md) | 優先順位・同順位、claim／complete、イベントとの競合 | Icarus |
| [64ビットカウンター](local-counter-snapshot/README.md) | 32ビットAPBからの一貫した読出し、スナップショット、桁上がり、一括反映 | Icarus |

## DMA・メモリ・順序制御

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [APB＋AXI4＋割り込みのDMA](local-dma/README.md) | 設定からコピー・完了通知まで、境界分割、中断、エラー | Icarus |
| [複数マスター接続](local-interconnect/README.md) | 2×2 AXI4の応答先、ID、仲裁、競合 | Icarus |
| [同一領域のアクセス競合](local-memory-order/README.md) | 複数マスターの読書き・書込み同士の競合を、書込み反映と読出しデータ取込みの時刻に基づいて照合 | Icarus |
| [リング式ディスクリプタDMA](local-descriptor-dma/README.md) | 既存DMAへの接続、リング巡回、取得エラー、中断、IRQ | Icarus |
| [DMAリングの所有権](local-dma-ownership/README.md) | 公開・実行・完了返却・回収、処理中の追加、再利用 | Icarus |
| [メモリ⇄Stream DMA](local-stream-dma/README.md) | 有効バイト、パケット終端、待ち、エラー時の残存範囲 | Icarus |
| [DRAMコマンド制御](local-dram/README.md) | 行ヒット・行競合、コマンド間隔、書込み回復、リフレッシュと応答保持、実コマンドによるメモリ照合 | Icarus |
| [小規模キャッシュとDMA](local-cache-dma/README.md) | write-back、部分書込み、clean／invalidateとデータの可視性 | Icarus |
| [ストアバッファとFENCE](local-store-buffer/README.md) | ストアの受理と可視性、自分の最新ストアからの転送、リトマス試験の結果集合、FENCEで禁止する結果 | Icarus＋Python |
| [2クライアントのキャッシュコヒーレンシ](local-cache-coherence/README.md) | MSIを簡略化した回路の無効化・dirtyデータの受渡し・追出しを、キャッシュのないメモリモデルと照合 | Icarus |
| [AXI4の応答順序入れ替え](local-axi-reorder/README.md) | 異なるID間の応答入れ替え、同じID内の順序、B／Rの保持 | Icarus |

## CDC・クロック・リセット・低電力

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [非同期FIFO](local-async-fifo/README.md) | クロック比・位相・ジッター、同期段数、参照キュー、同期遅延を含むフラグ | Icarus |
| [非同期APBブリッジ](local-cdc-bridge/README.md) | 要求／応答FIFOとAPBの接続、片側リセット時の全体破棄 | Icarus |
| [CDCハンドシェイク](local-cdc-handshake/README.md) | 複数ビットの4相req/ack、パルス同期、リセットの非同期アサート・同期デアサート | Icarus |
| [クロック停止とリセット](local-clock-reset/README.md) | 処理の排出・停止・再開、停止中のリセット、同期解除 | Icarus |
| [低電力制御](local-power/README.md) | 排出・隔離・状態保持・復帰のRTL動作モデル（UPF実行は対象外） | Icarus |
| [複数クロックと個別リセットの上位UVM](local-uvm-multiclock/README.md) | 片側リセット、解除順序、時刻順の観測、取消・古い応答・復帰、3種類のクロック条件 | UVM |

## 演算・故障注入・保護・性能・DFT

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [C++参照モデルとFIR](local-cpp-reference/README.md) | 3タップFIR、8／12ビット、丸め・飽和、入力受付、提示時刻、待ち・リセット、参照モデルへの故障注入 | Verilator＋C++17 |
| [固定小数点DSP](local-dsp/README.md) | 2タップFIRの符号、丸め、上下限、飽和、履歴 | Icarus |
| [ECCの故障注入](local-ecc/README.md) | SECDEDの誤りなし・1ビット誤り・2ビット誤りの全数検査、訂正・検出、保証範囲外の診断 | Icarus |
| [ECC付きメモリ](local-ecc-memory/README.md) | 読出し修復、スクラビング、通常書込みとの競合 | Icarus |
| [SHA-256](local-sha256/README.md) | 最大119バイトのパディング、1／2ブロックの連鎖、反復演算、hashlibとの照合、結果保持 | Icarus |
| [パケットCRC](local-packet-crc/README.md) | 独立した多項式除算と既知ベクトルによる生成・受信値検査 | Icarus |
| [MBIST・March C−](local-mbist/README.md) | ビットセルの故障モデル、10N操作、最初の失敗位置、再開 | Icarus |
| [JTAG TAP・境界走査](local-jtag-tap/README.md) | 16状態、IR／DR、IDCODE、BYPASS、SAMPLE/PRELOAD、EXTEST | Icarus |
| [内部スキャンとATPG](local-scan-atpg/README.md) | ロード・キャプチャ・アンロード、14単一縮退故障の分類、生成パターンによる検出可能な13故障の観測 | Icarus＋Python |
| [アクセス保護](local-access-control/README.md) | PPROT、設定ロック、禁止アクセスへのエラー応答と状態が更新されないこと | Icarus |
| [セキュリティ・ライフサイクル](local-secure-lifecycle/README.md) | セキュア属性、ロック、デバッグ鍵の試行制限、タンパー時の鍵消去 | Icarus |
| [ロックステップ監視](local-lockstep-monitor/README.md) | 2つの小規模演算コアの比較、故障注入、安全状態、復帰時の再同期、不正命令 | Icarus |
| [性能モニター](local-performance-monitor/README.md) | アウトスタンディング数、最大レイテンシ、測定区間の完了数・経過サイクル、不正応答 | Icarus |
| [タイムアウト復旧](local-recovery/README.md) | 古い応答の破棄、期限と応答の競合、タグ枯渇、下位回路も含むリセット | Icarus |

## AI用回路

推論アクセラレータを構成する回路です。各例は、推論回路で誤りやすい点（時間合わせ、丸め規則、近似誤差、画像の端、選択の正しさ）を1つずつ中心に取り上げます。[まとめて実行する手順](local-ai-regression/README.md)もあります。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [INT8シストリックアレイ](local-systolic-array/README.md) | 入力のずらしとそろえ直し、全体停止、重み更新と処理中データの競合、16ビットを超える累算 | Icarus |
| [INT32→INT8の再量子化](local-requantize/README.md) | 出典から書き下した2段階の丸め、全32シフトでのタイ、上下限、設定の取り込み時点、空き段の利用 | Icarus |
| [区分線形の活性化関数](local-activation/README.md) | 誤差の上限による判定、全4096入力、緩い上限で見逃す変異の診断 | Icarus |
| [畳み込みのラインバッファ](local-conv-window/README.md) | 3×3窓の端・角、ストライド、フレーム終わりの排出、連続フレーム、等価変異 | Icarus |
| [Top-K選択](local-topk/README.md) | ソーティングネットワークの安定な上位K個を、すべての入力についてフォーマルに証明 | フォーマル＋Icarus |
| [FP16／MXFP8／MXFP4のGEMM・量子化](local-mxfp4/README.md) | 設計仕様とRTLの取り込み・精度拡張、厳密有理数モデルによるビット照合、RNE・FTZ・NaN、GEMMの完了時点、FIFO・near/far・gradual underflow | Verilator＋Z3 |

## ネットワーク・パケット処理

[検証手順](../docs/method/network-verification.md)で、層ごとのヘッダー、フレーム境界、停止できる場所、破棄、所有権、完了通知を分けて学びます。外部Ethernetとチップ内のパケット通信は、それぞれのプロトコルと適用範囲を確認します。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [Ethernet FCS・ARP・IPv4／UDPエコーIP](local-network-echo/README.md) | 停止できないRX、2フレームキュー、満杯・サイズ超過の全体破棄、FCS・長さ・チェックサム、送信待ち | Icarus |
| [CPU付きネットワークSoC](local-network-soc/README.md) | ROM起動、CPUの返信・チェックサム・FCS生成、共有RAM、AHB-Lite／APB／AXI4 DMA、所有権とIRQ、エラー・再起動 | Icarus |
| [パケットスイッチ](local-packet-switch/README.md) | パケット単位の経路・占有・仲裁・解放 | Icarus |
| [クレジット方式のリンク](local-credit-link/README.md) | 仮想チャネル、送信許可、クレジット返却、停止と回復 | Icarus |
| [CRC・ACK・再送リンク](local-retry-link/README.md) | 教材固有の再送と重複排除、消失・破損・再送上限 | Icarus |
| [パケットCRC](local-packet-crc/README.md) | CRC-8の独立モデル・既知ベクトル。Ethernet FCSのCRC-32と区別 | Icarus |
| [AXI4-Stream](local-axis/README.md)／[Stream DMA](local-stream-dma/README.md) | パケット終端、有効バイト、待ち、メモリとの転送 | Icarus |

## 航空宇宙・高信頼システム

[検証手順](../docs/method/aerospace-verification.md)から、故障モデル、検出・訂正・封じ込め・復旧、正常機能への副作用を整理します。航空向け開発保証と宇宙向けの工学・製品保証を分け、RTL上の学習例の実行結果と、実機評価・認証への適合を区別します。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [TMR制御レジスタ](local-tmr/README.md) | 3系統の多数決、不一致、修復と書込み、全系統・全ビット位置、誤多数決・共通原因の限界 | Icarus |
| [FDIRサブシステム](local-fdir/README.md) | TMR上限・SECDED RAM・ウォッチドッグの接続、命令取消、出力抑止、原因のOR、保守修復と全走査による復帰 | Icarus |
| [ECCの故障注入](local-ecc/README.md)／[ECCメモリ](local-ecc-memory/README.md) | SECDEDの訂正・検出・保証外、スクラビングと競合 | Icarus |
| [ロックステップ監視](local-lockstep-monitor/README.md) | 比較・封じ込め・再同期 | Icarus |
| [タイマー・ウォッチドッグ](local-timer-watchdog/README.md) | 期限、kick、通知、リセット要求 | Icarus |

## ロボティクス・モーション制御

[検証手順](../docs/method/robotics-verification.md)で、センサー取得、制御演算、出力反映、プラント、異常停止の時点を分けます。既存の固定小数点DSP・画像処理・通信・監視と、閉ループの時間関係をつなげる分野です。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [PWM・直交エンコーダ](local-motion-io/README.md) | 相補出力、デッドタイム、周期境界の原子更新、Gray復号、フィルター、不正遷移、位置の折返し | Icarus |
| [1軸の閉ループ制御](local-motion-control/README.md) | 固定小数点PI、アンチワインドアップ、実PWMで駆動する簡易プラント、追従・逆転・負荷、期限・停止・再開 | Icarus |
| [C++参照モデルとFIR](local-cpp-reference/README.md) | 3タップFIR、8／12ビット、丸め・飽和、入力受付、提示時刻、待ち・リセット、参照モデルへの故障注入 | Verilator＋C++17 |
| [固定小数点DSP](local-dsp/README.md) | 符号、丸め、飽和、履歴 | Icarus |
| [SPI](local-spi/README.md)／[I²C](local-i2c/README.md) | センサー等の通信のモード、応答、異常 | Icarus |
| [画像処理](#画像処理)／[FDIR](local-fdir/README.md) | 計測値の処理、監視、取消、復帰へ発展 | Icarus |

## オートモーティブ

[検証手順](../docs/method/automotive-verification.md)で、通信の完全性・順序・更新期限、CPUのサービス窓、故障時の指令取消・出力抑止・復帰を整理します。車載バスやAUTOSARプロファイルへの適合と、教材の論理検証を区別します。

車載では使用環境と期間にわたる信頼性に加え、故障時の危険を抑える機能安全も求められます。[信頼性・品質・可用性・機能安全の違い](../docs/method/automotive-verification.md#信頼性品質可用性機能安全を分ける)と、AEC-Q100の部品評価・ISO 16750の環境評価・RTL検証の役割を、手順書の冒頭にまとめています。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [E2E通信保護](local-e2e-guard/README.md) | CRC-8/SAE-J1850、Data ID、番号・重複・欠落・折返し、出力待ち、初期化 | Icarus |
| [小規模ECU](local-automotive-ecu/README.md) | 通信保護RTLの実接続、窓付きウォッチドッグ、指令の更新期限、範囲、取消・出力抑止、許可付き復帰 | Icarus |
| [ロックステップ監視](local-lockstep-monitor/README.md)／[ECCメモリ](local-ecc-memory/README.md) | 不一致の封じ込め、再同期、訂正・検出、スクラブ | Icarus |
| [モーションI/O](local-motion-io/README.md)／[閉ループ制御](local-motion-control/README.md) | センサー、固定小数点演算、PWM、停止・再開 | Icarus |
| [SPICEとの協調](local-spice-cosim/README.md) | ngspiceで解く線形RC回路とデジタル制御の時刻・変換・応答 | Verilator＋C++17＋ngspice |

## アナログ・デジタル協調

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [RC電圧制御とSPICE](local-spice-cosim/README.md) | ngspiceで解く線形RC回路とRTLの閉ループ、ADC／DAC接続、時刻同期、解析解、回路定数・接続・制御の故障注入 | Verilator＋C++17＋ngspice共有ライブラリー |

## 画像処理

ラインメモリから窓を作る単体回路、画素演算を含むIP、CPUから実行するSoCへ進む題材です。[画像処理の検証手順](../docs/method/image-processing-verification.md)で、座標・端・飽和・待ち・フレーム境界と、転送・通知の契約を整理します。畳み込みの窓生成はAI用回路の題材とも共通です。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [畳み込みのラインバッファ](local-conv-window/README.md) | 2ライン分の履歴、3×3窓、端・角、ストライド、フレーム排出 | Icarus |
| [ラインメモリ付きSobel IP](local-image-sobel/README.md) | ゼロパディング、符号付き演算と飽和、全画素比較、待ち、連続フレーム、処理中リセット | Icarus |
| [CPU付き画像処理SoC](local-image-soc/README.md) | ROM起動、共有RAM、AHB-Lite／APB／AXI4、DMA、エラー・再起動、最終B応答とIRQ、CPUの結果確認 | Icarus |

## プロセッサ

RISC-Vの命令・保護機構、プロセッサを構成する回路、ソフトウェアから動かすSoCの11例です。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [RISC-VコアとISSの逐次比較](local-riscv-iss/README.md) | 5段パイプラインの退出命令をISSと1命令ずつ照合、転送・ロード直後の使用・分岐の取消し・メモリ待ちとの重なり、固定とランダムの命令列 | Icarus |
| [CPU付き画像処理SoC](local-image-soc/README.md) | CPUがROMから起動して画像DMAを設定し、割り込みから復帰してRAMの全画素を確認 | Icarus |
| [CPU付きネットワークSoC](local-network-soc/README.md) | CPUがRX割り込み後にARP／UDP返信とチェックサム・FCSを作り、DMA送信と所有権返却を行う | Icarus |
| [分岐予測器](local-branch-predictor/README.md) | 予測しない・静的・動的の3構成で退出の列がISSと一致すること、性能カウンターの照合、予測外れからの回復、結果を変えない性能の誤り | Icarus |
| [バイト・ハーフワードのロード・ストア](local-load-store/README.md) | 全サイズ・全レーンのアクセス、符号拡張とゼロ拡張、サブワードのストアの書込み位置、ロードした値の転送をISSと照合 | Icarus |
| [例外と割り込み](local-riscv-traps/README.md) | 不正な命令・ECALL・境界に合わないロード／ストアの精密な例外、外部割り込みを受け付ける位置、MRET、CSRの読み書きをISSと照合、予測器との組合せ | Icarus |
| [RISC-VのPMP判定](local-riscv-pmp/README.md) | TOR／NA4／NAPOT、最優先の領域がアクセス全体を覆うこと、Mモード・ロック・TOR下限の保護（4エントリーの縮小モデル） | Icarus |
| [Sv32ページテーブルウォーク](local-sv32/README.md) | 34ビットのPTE読出し・物理アドレス、4KiB／4MiBページ、SUM／MXR・A／D・PTEエラーとページフォルトの区別 | Icarus |
| [TLB＋Sv32ウォーカー](local-tlb/README.md) | ASID・4KiB／4MiBタグ・権限、グローバル変換、処理の排出後のSFENCE.VMAと古い変換の無効化 | Icarus |
| [RISC-Vの命令デコーダ](local-riscv-decoder/README.md) | 公式の命令表（riscv-opcodes）を基に、全2^32命令語の合法性判定と、合法命令の種別・即値・レジスタ使用信号を証明 | フォーマル＋Icarus |
| [多サイクル除算器](local-divider/README.md) | 0除算・オーバーフロー・剰余の符号・短い経路の境目・取消しの優先順位、32ビットのシミュレーションと4・8ビットの全入力の証明、補助不変条件と帰納法の深さ | Icarus＋フォーマル |

## 静的タイミング解析

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [OpenSTAによるSTA](local-sta/README.md) | 架空LibertyとSDCによるsetup／hold解析、手計算との照合、制約漏れ・過剰なfalse pathによる経路消失の検出 | OpenSTA |

## フォーマル検証・等価性・反例再現

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [公平性と最終完了](local-liveness/README.md) | 期限なしの進行、liveness-to-safetyと非有界PDR、無限待機の反例再生 | 固定版OSS CAD Suite |
| [FIFOのフォーマル検証](local-fifo-formal/README.md) | 制御の非有界証明、データの有界検査、到達性、意図的な誤実装と過剰な仮定の検出 | フォーマル |
| [AHB-Lite／AXI4-Liteのフォーマル検証](local-bus-formal/README.md) | 安全性の非有界証明、深さ12のデータBMC、到達性、変異検出 | フォーマル |
| [AXI4のフォーマル検証](local-axi4-formal/README.md) | 小規模メモリ構成の制御証明、条件を限定したデータBMC、到達性 | フォーマル |
| [FIFOの等価性検証](local-equivalence/README.md) | 最適化前後のmiterによる比較、意図的な誤実装に対する反例、仮定の確認 | フォーマル |
| [進行条件と完了期限](local-progress/README.md) | 環境の進行条件を明示した期限の検証、条件を外した場合の反例 | フォーマル |
| [フォーマル反例の再現](local-formal-replay/README.md) | Yosys Witnessを外部入力へ変換し、内部状態をforceせずシミュレーション再現 | フォーマル＋Icarus |
| [定時間比較・情報の流れ](local-constant-time/README.md) | 独立した秘密値を持つ2実行の公開信号・タイミングの一致、固定レイテンシ、比較結果の明示的な公開 | フォーマル＋Icarus |
| [SoCの接続性](local-connectivity/README.md) | 接続表から生成した検査回路で、ブロックをブラックボックスにした上位配線を証明、表の漏れ・幅の検査、割り込み番号・端子の切替え・デバッグ信号の遮断 | フォーマル |
| [仮定・保証と分割証明](local-compositional-formal/README.md) | 送信側・受信側・配線の契約、結合実装の検算、証明依存・欠落・版・循環の照合 | フォーマル |

## SVA・UVM・仕様生成・ソフトウェア連携・検証効率

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [UVMの順不同応答](local-uvm-outstanding/README.md) | 4件同時未完了、ID・token、応答順の追越し、再利用、reset取消し、独立台帳 | UVM |
| [MCYの自動ミューテーション](local-auto-mutation/README.md) | 自動生成した同じ候補を弱い／強いテストと非有界等価性で分類 | Icarus＋固定版OSS CAD Suite |
| [SVAのアサーションとカバー](local-sva/README.md) | assert／cover、前件が成立しない場合の診断、違反注入、ネイティブcoverage.datとの照合 | Verilator |
| [SystemVerilog UVM・RAL](local-uvm/README.md) | APB agent・monitor・独立したスコアボード、RALとレジスタ操作 | UVM |
| [passive・active UVMへの移行](local-uvm-migration/README.md) | 設定・factory・SVA報告、sequence・driverでの同一入力再生、14項目・20／21目標の維持、追加RAL検査 | Icarus＋UVM |
| [複数UVM agentの協調](local-uvm-coordination/README.md) | APB設定・GAIN・ready、観測の到着順、同時受理・保持・取消、23 binと4 SVA目標 | UVM |
| [UVM子環境と上位RALの再利用](local-uvm-hierarchy/README.md) | 共通driver、受動的な子環境、二つのsubmapと配置変更、上位virtual sequence、独立した読戻し | UVM |
| [検証項目表と結果の自動照合](local-plan-traceability/README.md) | 仕様・6要求・6項目・native SVAの対応、構成と版、未実行・不足・古い証跡の拒否 | Verilator |
| [仕様変更の再検証](local-spec-change/README.md) | APB＋割り込みのr1／r2を同じ入力で比較、古い期待値・SVA・証跡の拒否、native SVAと行カバレッジ | Icarus＋Verilator |
| [初回失敗と再実行のレポート](local-regression-report/README.md) | 実際のFIFO時間切れ、同じ計画の再実行、全履歴・最後の試行・未達の照合 | Icarus |
| [全DUTの共通lintと警告管理](local-lint/README.md) | 明示した構成・共有ソース、指摘の追加・解消・除外の失効、幅・ラッチ・暗黙ネット等の負例 | Verilator |
| [失敗解析と修正後の再実行](local-failure-triage/README.md) | RTL・期待値・SVA設定・比較器の無効化・ツール不足・時間切れの切分け、同じ入力での回帰確認、不具合票 | Verilator |
| [AIの悪い提案をレビューする](local-ai-review/README.md) | 要求抜け、誤った`$past`、空虚な成立、DUTと参照モデルの相関した誤り。APIキー不要 | Verilator |
| [コードカバレッジの未達分析](local-code-coverage/README.md) | 行・分岐・式・toggle・FSM、追加試験、DB統合・注釈、カバレッジ達成時の機能不正 | Verilator |
| [ネイティブ機能カバレッジ](local-functional-coverage/README.md) | DRAM・SHA-256・スイッチのcoverpoint／cross、DBのbin集合・ヒット数、計測不足の拒否 | Verilator |
| [UVMの制約付きランダム検証](local-uvm-random/README.md) | rand・constraint・randomize、ネイティブcovergroup、seedの再現 | UVM＋Z3 |
| [SystemRDLによる仕様生成](local-register-spec/README.md) | RTL・Cヘッダー・RALの生成、生成物の構造・属性・動作を、独立に定めた期待値と照合 | SystemRDL＋Icarus＋UVM＋C |
| [生成RTL＋UVM RALの結合](local-generated-ral/README.md) | フロントドアアクセス、独立したスコアボード、ミラー比較 | SystemRDL＋UVM |
| [Cドライバ＋DMA RTL](local-c-driver/README.md) | ホスト上のCからAPBで起動・監視し、実DMAのIRQ・エラー・復旧を確認 | Verilator＋C |
| [cocotbによるAPB検証](local-cocotb/README.md) | Pythonコルーチンによる刺激・位相モニター・独立したレジスタモデル | Icarus＋cocotb |
| [Icarus／Verilatorの差分検証](local-differential/README.md) | 共通入力の有効な観測を比較し、差分検出とX検査を別々に判定 | Icarus＋Verilator |
| [合成後ネットリストのシミュレーション](local-gate-sim/README.md) | 同じテストベンチをRTLとYosysの合成結果で実行、`translate_off`・`parallel_case`・初期値・ブロッキング代入による食い違い、Xの現れ方 | Icarus＋Yosys |
| [APB＋割り込みのクロス網羅と選択](local-apb-irq-coverage/README.md) | 2因子・重点・時間関係の実観測、既存目標の保持、追加ケースの選択と再実行の比較 | Icarus |
| [リグレッションの削減](local-reduction/README.md) | 全件・目標だけの選択・ストレス保持を比較し、実行量・目標・検出力を評価 | Icarus |
| [失敗した操作列の自動縮小](local-failure-reduction/README.md) | 同じチェッカーで失敗を再現し、単一操作削除に対する極小性を確認 | Icarus |
| [未達カバレッジからの刺激調整](local-coverage-feedback/README.md) | 観測に基づく刺激と固定分布のランダム刺激を同じサイクル予算で比較 | Icarus |

ランダム探索の重複管理・再現性・失敗ケースの固定回帰への移し方は、[管理の手順](../docs/method/random-search-management.md)と[既存例を使う演習](../docs/method/random-search-management-walkthrough.md)を参照してください。演習はFIFOの生成条件・入力を分類し、AXI4-Streamの縮小列を保存して新しくビルドしたRTLへ再生します。新しい登録例や統合nightlyのジョブを追加したものではありません。

各検証例は、教材として検証対象を限定しています。例えば、AXI4の例は仕様全体への適合性、CDCの論理シミュレーションは物理的なメタスタビリティやMTBFまでを保証するものではありません。要求カタログに定めたカバレッジ目標の達成、結果の正しさ、製品の検証完了は分けて判断します。

変更箇所から影響する例を選ぶ場合は[選択の手順](../tools/AFFECTED.md)を使えます。不明な入力や依存変更は全例へ戻します。毎晩の全例実行も維持します。

## 外部のオープンソースDV環境（参照例）

小規模な実行例から、実プロジェクトのCPU・演算IP・メモリー・バス・NIC・セキュリティIPのDV環境へ進むための参照例13件です。[読み方・依存・版の比較](../docs/method/open-source-dv-environments.md)では、公開された検証ソースと、実行に必要なツールを分けて説明します。

| 参照例 | 読む内容・小演習 | 実行条件と確認範囲 |
| --- | --- | --- |
| [Ibex DV](reference-ibex-dv/README.md) | 命令生成、メモリー応答、IRQ、RVFI、Spikeのコシミュレーション | 固定版のソース・設定を確認。フルUVMは未実行で、上流の手順には商用シミュレーター等が必要 |
| [CVA6](reference-cva6-dv/README.md) | 構成別の経路、Verilator／Spike、生成器とRTL側の設定、UVMの比較有効化 | 固定版のソース・設定を確認。RTL／ISS・フルUVMは未実行。選択する経路ごとに依存を確認 |
| [OpenTitan](reference-opentitan-dv/README.md) | UARTの計画・共通UVM環境・RAL・比較・カバレッジ。Pythonの計画操作ツールを使う手動演習 | 計画メタデータの抽出・照会・不具合再現と修正例を実行。IP／SoCのUVMは未実行 |
| [CV32系／CORE-V-VERIF](reference-core-v-verif/README.md) | E40Pを入口に、E40X・E40Sの専用DV、OBI・IRQ・debug・RVFI／RVVI・ISSの設定を読む | 固定ソース・設定を確認。CPUのRTL／ISS・フルUVMは未実行。対象コアとモデル・ツール条件を対で確認 |
| [CVFPU／cvfpu-uvm](reference-cvfpu-uvm/README.md) | 形式・丸め・例外フラグ、C++・MPFRモデル、ID・flush、比較・終了条件 | 構成・比較経路を確認。モデル構築・フルUVM・数値検算は未実行 |
| [HPDcache](reference-hpdcache/README.md) | SystemCの単体TBとUVMのサブシステム、メモリー応答・置換・未完了要求・待ち | 両経路のソースを確認。SystemC側にはSCV等も必要。構築・実行は未確認 |
| [Mirafra mBitsのVIP](reference-mirafra-vip/README.md) | APB／AXI4のBFM・比較、b2b・master・slave、DUTへ接続する責務 | ソース・回帰リスト・設定を確認。UVM・Verilator・加速の実行は未確認 |
| [PicoRV32](reference-picorv32/README.md) | 小さなCPUとメモリーの簡易TBに、値・順序・件数・時間上限の自動判定を追加する演習 | Icarusで上流の簡易TB、正常1件・負例2件を実行。全ISA・ISS・UVM・フォーマルの確認とは別 |
| [PULP AXI](reference-pulp-axi/README.md) | SVのランダムmaster／slave、クロスバーの比較、ID・待ち・未完了要求、構成とseedの回帰 | 固定ソース・比較の有効化・Questa等の条件を確認。上流TBは未実行 |
| [LiteDRAM](reference-litedram/README.md) | リフレッシュ・ECC、AXIフロントエンド、Python／Migenのシミュレーションとunittest | リフレッシュ・ECCの6テストを実行。全テスト・生成RTL・PHY・実機は未確認 |
| [Corundum](reference-corundum/README.md) | cocotbのパケット期待値、NIC・PCIe・DMA・キューの結合、構成行列とCI分割 | 固定ソース・比較・PythonとIcarusのCI条件を確認。RTL・実機は未実行 |
| [NVDLA](reference-nvdla/README.md) | AIアクセラレーターのトレース、入力・重み・レジスター・割り込み、出力メモリー比較 | `nvdlav1`を読解し、I/O修正をC++単体8条件で確認。RTL・演算Cモデルは未実行 |
| [Caliptra](reference-caliptra/README.md) | 暗号・鍵管理IP、SHA-512の期待ベクトル・予測器・比較器、zeroizeと機能カバレッジ | 固定ソース・接続・商用VIPを含む依存を確認。RTL・UVM・セキュリティ評価は未実施 |

13件は上流を読む参照例で、下記の130登録項目・108ルートジョブへ加算しません。手動演習では、OpenTitanの計画メタデータ、PicoRV32の限定したプログラムのRTL実行、LiteDRAMの6テストのMigenシミュレーションを扱います。NVDLAはI/O修正のC++単体8条件も確認しています。上流フルDVの成功やカバレッジ収束へ読み替えません。

## 集計と実行記録

実行数や過去の確認結果を調べる場合は、各例の実行記録と[PROVENANCE.md](../PROVENANCE.md)を参照してください。共通シミュレーションランナーの計画は58例・124構成、各検証例が出力するJUnit件数の合計はsmoke 875件／nightly 1123件です。フォーマル・UVMなどの別ランナー、親の集約判定、ランナー自身のセルフテストは別集計です。

[関連例の集約手順](../README.md#まとめて実行する手順)は親の判定と子の個別結果を持ちます。同じ実行を重複して件数へ加えないようにします。

[全例の統合ランナー](../tools/REGRESSION.md)は、記載構成の行列と集約の親子関係を登録表から読み込みます。UVM移行例はpassive・activeの両モードを別々に起動し、選択した範囲と判定を記録します。

現在の統合計画は、130登録項目・108ルートジョブです。nightly対応の個別例に加え、集約7本、全12フォーマル例、固定計画の共通lint・STAを含みます。[登録表](../tools/regressions.json)の種別で数えると、`formal`は子タスク1行を含めて13行、`aggregate`は共通lintの2行を含めて9行です。証明専用例の計画は23構成・182タスクです。MCYが各候補に対して実行する等価性証明は別集計です。画像処理の2例は独立したランナーで、単体IPのJUnitは18／22件、SoCは44／48件です。ネットワークの新2例も独立したランナーで、単体IPは30／34件、SoCは54／58件です。TMRとFDIRも独立したランナーで、JUnitはそれぞれ14／18件、56／60件です。モーションI/Oは28／32件、閉ループ制御は48／52件です。VCI・SoCLibは23／27件、C++参照モデルは22／26件、SPICE協調は25／29件です。E2E通信保護は24／28件、小規模ECUは30／34件です。いずれもsmoke／nightlyの順です。

共通lintの対象は124 RTLファイル・125モジュール・322構成です。画像処理の17構成に続き、ネットワークIP・SoCの15構成も警告0件です。TMR・FDIRの9構成と、モーション制御の12構成も警告0件です。C++・SPICEの4構成と、車載向けの新4構成も警告0件です。既存の487件（未解決439件・限定した除外48件）の指摘は維持し、差分なしの成功と警告0件を区別します。

各例の既定計画には正常動作・変異・診断があり、予定した反例や未到達の識別も成功と判定します。証明は各例のモデルと仮定の範囲、BMCは設定された深さまでの確認です。個別結果・親判定・lint・セルフテストを分けた実行数、設定、残る制限は[最新のレビューと確認記録](../PROVENANCE.md#verification-gaps-20261107)を参照してください。

## 初期の11例の構成

最初に作った11例は、共通ランナーができる前の例で、例ごとに独自のランナーを持ちます。ほかの例と同じく、このリポジトリを取得した手元の環境で実行します。

11例の構成と件数を下表に示します。APB・UART・割り込み結合検証の9構成の目標・変異・完了記録の照合結果は[結合例の実行記録](local-apb-uart/README.md#7-適用範囲と実行確認)に記載しています。

| 実行例 | 構成・対象 | smokeのJUnit件数 | nightlyのJUnit件数 |
| --- | --- | --- | --- |
| [IRQ・CDC](local-irq-cdc/README.md) | 1構成、要求8件・目標50件 | 38 | 41 |
| [FIFOランダム検証](local-fifo/README.md) | 6構成、深さ1／3／8×幅8／16 | 36（各6） | 48（各8） |
| [FIFOフォーマル検証](local-fifo-formal/README.md) | 2構成、幅8・深さ1／3 | 16（各8） | 16（各8） |
| [APBレジスタ検証](local-apb/README.md) | 3構成、待ち状態0／1／3 | 18（各6） | 24（各8） |
| [APB＋割り込み結合検証](local-apb-irq/README.md) | 3構成、待ち状態0／1／3 | 18（各6） | 24（各8） |
| [ready/validランダム検証](local-stream/README.md) | 4構成、深さ1／3×幅8／16 | 24（各6） | 32（各8） |
| [SVAのアサーションとカバー](local-sva/README.md) | 1構成、要求6件・カバー12目標 | 10 | 12 |
| [リグレッションの削減の比較](local-reduction/README.md) | 1構成、全件／選択／ストレス保持の比較 | 18（集約判定） | 18（集約判定） |
| [ラウンドロビン・アービタ](local-arbiter/README.md) | 3構成、要求元2／3／4 | 21（各7） | 27（各9） |
| [UARTランダム検証](local-uart/README.md) | 6構成、分周数8／16×パリティなし／偶数／奇数 | 40（各6／7） | 52（各8／9） |
| [APB・UART・割り込み結合検証](local-apb-uart/README.md) | 9構成、待ち状態0／1／3×パリティなし／偶数／奇数 | 72（各8） | 90（各10） |
| 合計 | 39構成 | 311 | 384 |

ランナーのセルフテストはIRQ 14件、FIFO 10件、フォーマル8件、APB 12件、APB＋割り込み12件、ready/valid 13件、SVA 12件、削減比較11件、アービタ13件、UART 13件、APB・UART・割り込み14件の計132テストで、上表のJUnit件数とは別です。nightlyでは、シミュレーションと削減比較の10例がランダム操作を増やし、フォーマル検証は通常実行と同じタスクを実行します。
