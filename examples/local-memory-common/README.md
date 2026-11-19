# RAMを使う4つの発展教材

[RAMのポート比較](../local-ram-ports/README.md)と[非同期画像パイプライン](../local-video-async/README.md)から進む教材です。

- [ECC付きRAMの部分書き込み](../local-ecc-rmw/README.md)：訂正した旧ワードへ指定バイトを反映し、ECCを再計算します。
- [画像のダブルバッファ](../local-video-double-buffer/README.md)：描画と表示を別クロックで動かし、フレーム境界で所有権を渡します。
- [同期RAM型の非同期FIFO](../local-sync-ram-fifo/README.md)：読出し待ちと先読みを含めて、valid/readyのデータ保持を確認します。
- [非整列アクセスとエンディアン変換](../local-unaligned-memory/README.md)：ワード境界をまたぐ転送、Byte enable、分割途中のエラーを検証します。

リポジトリのルートで次の1コマンドを実行すると、4例をまとめて回帰できます。

```sh
python3 tools/run_regression.py --example local-ecc-rmw --example local-video-double-buffer --example local-sync-ram-fifo --example local-unaligned-memory --profile nightly --jobs 2 --out artifacts/memory-integration-nightly
```

各例はSystemVerilog RTLと自己判定TBを持ち、Python 3・Icarus Verilog・vvpで実行します。追加Pythonパッケージは不要です。全体ランナーの準備と結果の読み方は[回帰手順](../../tools/REGRESSION.md)を参照してください。

## 共通の判定と証跡

[sim.py](sim.py)は[既存の証跡補助](../local-exploration-common/evidence.py)と[プロセス判定](../local-irq-cdc/run.py)を再利用します。各例の回路・期待値は共通化せず、それぞれの教材に置きます。

通常試験は終了コード0、唯一の`RESULT PASS checks=N`、予定件数と一致する唯一の`COUNT steps=N`を要求します。必須目標は成功した通常試験だけから集計します。意図した誤実装は指定した`CHECK_FAIL`と非ゼロ終了、または完了した画像ログに対する独立した画素・タイミング比較の不一致が必要です。ビルド失敗、無関係な異常終了、時間切れ、画像ログの欠落・破損は検出成功にしません。

各例で`--profile smoke|nightly`、`--seed`、`--timeout`、`--iverilog`、`--vvp`、`--waves`、`--out`を使えます。nightlyはseed・seed+1・seed+2を実行します。ECCと非整列アクセスはランダム操作数も増やし、FIFOは転送数を増やします。画像は画像内容と入力bubbleを3 seedで変えます。同じ版・構成・seedで再現できます。

出力先には`manifest.json`、ツールの版取得ログ、ビルドログ、ケース別の入力・実行ログ・`result.json`、`coverage.json`、`summary.json`、`junit.xml`を保存します。`--waves`指定時は各ケースに`trace.vcd`を保存します。画像はPPMとCSV、FIFOは占有量CSVも残します。`--out`は新しいディレクトリを指定し、既存の結果を上書きしません。入力・RTL・参照モデル・要求・共有補助のハッシュを記録し、実行中のソース変更を拒否します。

4例合計のJUnit判定はsmoke 54件、nightly 84件です。この中には16種類の意図した誤実装、構成別の必須目標、ツールとソースの確認を含みます。回路の操作数や画素数とは別の件数です。

4教材と共有補助のセルフテストは合計21件です。既知値のほか、X、誤期待値、画像の改変、破損ログ、欠落波形、無関係な異常終了を拒否することも確認します。実行した版・結果・未確認範囲は[実行記録](../../PROVENANCE.md#memory-integration-four)を参照してください。
