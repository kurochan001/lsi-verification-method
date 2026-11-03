# SVG図の一覧と編集方針

信号のエッジ、画素の座標、ID別の並び、回路の接続を位置関係で読むための図です。手順や構成のMermaid図、比較表に加えて、固定した配置が理解を助ける箇所で使います。

| SVG | 示すこと | 本文・実行例 |
| --- | --- | --- |
| [ready/validの保持波形](ready-valid-hold.svg) | 待ち中のvalid・data保持と、受理されるエッジ | [ready/validバッファ](../../examples/local-stream/README.md) |
| [3×3窓と画像端](image-window-padding.svg) | 画素座標、入力から窓が揃う位置、画像外の0 | [窓生成](../../examples/local-conv-window/README.md)／[Sobel IP](../../examples/local-image-sobel/README.md)／[検証手順](../method/image-processing-verification.md) |
| [観測時刻と通知順](observation-order.svg) | 通知の到着順を観測時刻順へ戻し、完了とresetを扱う | [複数クロックUVM](../../examples/local-uvm-multiclock/README.md)／[UVM実践設計](../method/uvm-practical-design.md) |
| [Grayポインターの観測](gray-pointer-sampling.svg) | 送信元の1 bit変化と、受信側が更新を飛び越す場合 | [非同期FIFO](../../examples/local-async-fifo/README.md) |
| [AXIのID別順序](axi-id-order.svg) | 同じID内の順序を保持し、異なるIDの応答を入れ替える | [AXI応答順序](../../examples/local-axi-reorder/README.md) |
| [RC回路と制御の戻り道](spice-rc-loop.svg) | Vdrive・Rplant・Cplantの接続と、ADC／RTL／DACの関係 | [SPICE協調例](../../examples/local-spice-cosim/README.md)／[検証手順](../method/spice-cosimulation.md) |

波形・時刻・座標・返却順は契約を説明するための例です。保存した実測波形、全構成の検証結果、物理的なCDCやアナログ特性の保証を表すものではありません。適用条件と実行確認の範囲は、本文と各例の証跡を参照してください。

SVG自体が編集できるベクターの原本です。`viewBox`、`title`・`desc`、本文の代替テキストを保ち、色だけに意味を持たせません。外部フォント・画像・スクリプトには依存せず、図中の数値や関係を変更したら本文・仕様・対応するソースを照合します。編集後はSVGの構文と、本文に埋め込んだ表示の両方を確認します。
