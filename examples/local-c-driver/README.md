# CドライバとDMA RTLを結合検証する

C11でコンパイルしたドライバから、[既存DMA RTL](../local-dma/README.md)をAPBで設定・起動し、完了・割込み・エラー・復旧を確認します。Cコードを説明だけで載せず、生成したオブジェクトをVerilatorの実行ファイルへリンクします。

## 構成と契約

```text
Cドライバ → read32／write32コールバック → APB信号 → DMA RTL
                                                   ↓ AXI4
                                           C++バイトメモリモデル
```

`dma_submit`は転送元・転送先のバイトアドレスと**ワード数**を設定します。`dma_wait`はSTATUSをポーリングし、正常・ハードウェアエラー・中断・ソフトウェアの待ち切れを区別します。max_pollは状態読出し回数で、実時間やクロック数ではありません。

`dma_abort`はコマンドを出し、`dma_irq_enable`は出力をマスクし、`dma_ack_irq`はpendingを確認してクリアします。割込み出力とpendingを照合してCのACK関数を呼びますが、CPUの割込み例外に入る試験ではありません。

C++はMMIOを実際のAPBサイクルへ変換し、AXI要求を受ける8KiBの参照メモリを動かします。初期値は番地ごとのパターンです。要求番地、ID、境界、Wデータ・ストローブ・LAST、コピーしたワード数、終了後の全メモリを照合します。DUT内部の状態を読んで期待値を作りません。

## 試験

固定試験は通常コピー、転送元／先の4KiB境界、ゼロ長、非整列要求、Rエラー、IRQマスクとACKです。タイムアウト試験ではAR受付を止め、Cの待ち切れを確認してabortを出します。その後にAR受付を再開し、受付待ちだった要求を完了・排出してから、同じ回路で次のコピーを行います。リセットで成功状態へ置き換える復旧ではありません。

ランダム試験はコピー長・番地・初期値と要求側の待ちを変えます。[要求カタログ](requirements.json)は3要求・8目標。4負試験は**Cコード側**へ、ワード数の単位間違い、busyをdoneと読む誤り、IRQクリア先の誤り、エラーを成功として返す誤りを入れます。DMA RTLの4変異とは別の計画です。

## 実行

POSIX、Python 3.10以上、C／C++コンパイラー、make、Verilatorを使います。Pythonの追加パッケージは不要です。

```sh
python3 examples/local-c-driver/run.py
python3 examples/local-c-driver/run.py --profile nightly
python3 -m unittest discover -s examples/local-c-driver/tests -v
```

構成は`host-c`。smokeは固定8シナリオ＋24コピー×1 seed、nightlyは固定8＋200×3 seedを通常実行します。固定のタイムアウト・中断・再開シナリオにはstartが2回あります。checksはシナリオ数、JUnitは7／9件です。

[共通ホストランナー](../local-host-common/README.md)が、Cのコンパイルコマンド・オブジェクト、Verilatorビルド、入力、VCD、件数、要求カバーと結果を保存します。C単体APIのテストも含め、確認テストは4件です。

CPU命令、OS、実MMIOのメモリ属性・バリア、キャッシュ整合性、割込み例外の配送、実機ドライバの検証は含めません。ホスト上でCを実行してRTLへのアクセス手順を照合する例です。
