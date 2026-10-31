# 検証例一覧

回路・検証方式ごとに、対象範囲と主な検証内容、必要なツールをまとめています。個別の実行手順・合格条件・証跡は各例のREADMEを参照してください。

検証の考え方は[検証手法の案内](../README.md#検証の進め方)、共通の準備と実行は[ルートREADME](../README.md#準備と実行)から確認できます。

- [バス・レジスタ・アドレス](#バスレジスタアドレス)
- [FIFO・通信・仲裁](#fifo通信仲裁)
- [割り込み・タイマー・周辺機能の結合](#割り込みタイマー周辺機能の結合)
- [DMA・メモリ・順序制御](#dmaメモリ順序制御)
- [CDC・クロック・リセット・低電力](#cdcクロックリセット低電力)
- [演算・故障注入・保護・性能・DFT](#演算故障注入保護性能dft)
- [AI用回路](#ai用回路)
- [プロセッサ](#プロセッサ)
- [静的タイミング解析](#静的タイミング解析)
- [フォーマル検証・等価性・反例再現](#フォーマル検証等価性反例再現)
- [SVA・UVM・仕様生成・ソフトウェア連携・検証効率](#svauvm仕様生成ソフトウェア連携検証効率)

「主なツール」はPythonに加えて必要な環境です。IcarusはIcarus Verilog、フォーマルはYosys・SymbiYosys（SBY）・Z3、UVMはVerilator・C++20環境・外部のAccellera UVMを指します。Verilatorを使う例にはC++コンパイラとmakeも必要です。詳細な版・追加パッケージ・セットアップは各手順を参照してください。

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

## 演算・故障注入・保護・性能・DFT

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
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

## プロセッサ

RISC-Vの命令・保護機構と、プロセッサを構成する回路の9例です。

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [RISC-VコアとISSの逐次比較](local-riscv-iss/README.md) | 5段パイプラインの退出命令をISSと1命令ずつ照合、転送・ロード直後の使用・分岐の取消し・メモリ待ちとの重なり、固定とランダムの命令列 | Icarus |
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
| [FIFOのフォーマル検証](local-fifo-formal/README.md) | 制御の非有界証明、データの有界検査、到達性、意図的な誤実装と過剰な仮定の検出 | フォーマル |
| [AHB-Lite／AXI4-Liteのフォーマル検証](local-bus-formal/README.md) | 安全性の非有界証明、深さ12のデータBMC、到達性、変異検出 | フォーマル |
| [AXI4のフォーマル検証](local-axi4-formal/README.md) | 小規模メモリ構成の制御証明、条件を限定したデータBMC、到達性 | フォーマル |
| [FIFOの等価性検証](local-equivalence/README.md) | 最適化前後のmiterによる比較、意図的な誤実装に対する反例、仮定の確認 | フォーマル |
| [進行条件と完了期限](local-progress/README.md) | 環境の進行条件を明示した期限の検証、条件を外した場合の反例 | フォーマル |
| [フォーマル反例の再現](local-formal-replay/README.md) | Yosys Witnessを外部入力へ変換し、内部状態をforceせずシミュレーション再現 | フォーマル＋Icarus |
| [定時間比較・情報の流れ](local-constant-time/README.md) | 独立した秘密値を持つ2実行の公開信号・タイミングの一致、固定レイテンシ、比較結果の明示的な公開 | フォーマル＋Icarus |
| [SoCの接続性](local-connectivity/README.md) | 接続表から生成した検査回路で、ブロックをブラックボックスにした上位配線を証明、表の漏れ・幅の検査、割り込み番号・端子の切替え・デバッグ信号の遮断 | フォーマル |

## SVA・UVM・仕様生成・ソフトウェア連携・検証効率

| 検証例 | 主な検証内容 | 主なツール |
| --- | --- | --- |
| [SVAのアサーションとカバー](local-sva/README.md) | assert／cover、前件が成立しない場合の診断、違反注入、ネイティブcoverage.datとの照合 | Verilator |
| [SystemVerilog UVM・RAL](local-uvm/README.md) | APB agent・monitor・独立したスコアボード、RALとレジスタ操作 | UVM |
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

各検証例は、教材として検証対象を限定しています。例えば、AXI4の例は仕様全体への適合性、CDCの論理シミュレーションは物理的なメタスタビリティやMTBFまでを保証するものではありません。要求カタログに定めたカバレッジ目標の達成、結果の正しさ、製品の検証完了は分けて判断します。

## 集計と実行記録

実行数や過去の確認結果を調べる場合は、各例の実行記録と[PROVENANCE.md](../PROVENANCE.md)を参照してください。共通シミュレーションランナーの計画は58例・124構成、各検証例が出力するJUnit件数の合計はsmoke 874件／nightly 1122件です。フォーマル・UVMなどの別ランナー、親の集約判定、ランナー自身のセルフテストは別集計です。

[関連例の集約手順](../README.md#まとめて実行する手順)は親の判定と子の個別結果を持ちます。同じ実行を重複して件数へ加えないようにします。

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
