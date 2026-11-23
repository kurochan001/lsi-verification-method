# 12分野の検証例をまとめて実行する

各例は2構成の実行可能なRTL、Pythonの期待値モデル、要求ごとの観測目標、4種類の変異を備えています。子の個別記録には失敗したケースの波形、刺激、検出ラベルが残ります。

| 題材 | 確かめる動作 |
| --- | --- |
| [PLIC](../local-plic/README.md) | 優先順位が同じ割り込みの選択、請求・完了と再発火 |
| [パイプライン乗算器](../local-mul-pipe/README.md) | 積と有効ビットが指定の段数をそろって通過すること |
| [RVWMOのSBリトマス](../local-rvwmo-litmus/README.md) | フェンスを置いた場合の禁止結果と、外した場合の到達例 |
| [IOMMU](../local-iommu/README.md) | アドレス変換、権限エラー、TLB無効化 |
| [フラッシュ制御](../local-flash-ctrl/README.md) | シリアル書込み・消去、書込み許可、ビジー時間、XIP読出し |
| [RTC](../local-rtc/README.md) | 時刻更新、アラーム、外部イベントの時刻取得 |
| [クロック切替](../local-clock-switch/README.md) | 入力クロックの選択・停止・再開と分周比の更新 |
| [CAN FD](../local-canfd/README.md) | 送信フレームのスタッフ、CRC、ビットレート切替 |
| [USB線路符号](../local-usb-linecode/README.md) | トークンとデータのNRZI、ビットスタッフィング、受信誤り |
| [2×2メッシュNoC](../local-noc-mesh/README.md) | XYルーティング、出口の停止、受理したパケットの排出 |
| [JTAG–APB](../local-jtag-apb/README.md) | TAP操作によるAPB転送、待ちとエラーの読戻し |
| [ハードウェアセマフォ](../local-hw-semaphore/README.md) | 所有権の獲得・解放、フェンス通知、割り込み回数の制限 |

## 実行

出力には新しいディレクトリを指定します。単独例はそれぞれの `run.py` で実行できます。

```sh
python3 tools/run_regression.py --example local-domain-expansion --profile smoke --out artifacts/domain-smoke
python3 tools/run_regression.py --example local-domain-expansion --profile nightly --out artifacts/domain-nightly
python3 -m unittest discover -s examples/local-domain-expansion/tests -v
```

smokeは各構成で固定刺激1件・ランダム1 seed・変異4件、nightlyはランダムを3 seedに増やします。子12例の実行は144件／192件で、構成ごとのカバレッジ判定24件を足したJUnitは168件／216件です。親のJUnitには子の合否が12件残ります。

集約は最後の子が終わった時点で、全子の終了状態、プロファイル・seed、実行数と変異検出数、カバレッジ、JUnit、ソースのハッシュを照合します。RVWMOとパイプライン乗算器の形式検証は各例の単体テストから起動します。各回路が扱うプロトコル機能やタイミングの範囲は、それぞれのREADMEに記載しています。
