# 未完了数・レイテンシ・測定窓を性能モニターで検証する

タグ付き要求と応答を追跡し、未完了数、完了数、レイテンシの最大値、測定窓の完了数と経過サイクルを数える回路です。性能の平均値だけでなく、最大待ち、同時未完了、測定窓の境界、不正な応答を分けて確認します。

## 測定の関係

```mermaid
flowchart LR
  accTitle: 性能モニターの測定経路
  accDescr: 要求のタグと開始時刻を保持し、応答のタグでレイテンシと完了数を更新する。
  Q["要求<br/>valid・tag"] --> O["未完了スロット<br/>開始時刻"]
  R["応答<br/>valid・tag"] --> C["対応付け"]
  O --> C
  C --> L["レイテンシ<br/>現在cycle − 開始cycle"]
  L --> M["完了数・最大値"]
  L --> W["測定窓<br/>done・cycles・max"]
  S["start / stop"] --> W
```

図はタグで対応付ける測定の構成です。バスのプロトコルや仲裁方式を再現した図ではありません。

## 仕様

- 最大`SLOTS`件の要求を同時に保持します。同じタグが未完了の間、そのタグの要求は`req_ready=0`で止まります。
- 応答が未完了タグと一致すれば、`latency = cycle - start_time[tag]`を1件分として加算します。応答と要求が同じサイクルでも、更新前の未完了状態で判定します。
- `total_done`と`total_max`はリセットまで保持します。`total_max`は8ビットです。
- `start`は測定窓の`window_done`・`window_cycles`・`window_max`と`error`をクリアし、窓を開きます。同じサイクルの応答は全体統計だけへ加算し、窓へは加算しません。
- `stop`はそのサイクルまで窓へ加算し、次のサイクルから閉じます。`start`と`stop`が同時なら`start`を優先します。
- 未完了でないタグへの応答は`error=1`にし、`start`またはリセットまで保持します。
- `window_cycles`は窓が開いているサイクル数です。完了数だけで帯域を判断せず、経過サイクルと併記します。

## 独立した期待値と構成

Pythonはスロットの開始時刻と窓の状態を保持し、RTLのカウンター更新順を写さずに各サイクルの期待値を求めます。固定シナリオは連続要求、全スロット使用、タグの入替え、長い待ち、不正応答、窓の開始・停止、リセット復帰を含みます。

| 構成 | 同時未完了 |
| --- | --- |
| `slots2` | 2 |
| `slots4` | 4 |

[要求カタログ](requirements.json)は4要求・13目標です。ランダム刺激は現在の未完了タグを参照して応答を選ぶため、合法な完了と不正な応答の両方を作ります。

## 意図的な誤実装

| 番号 | 誤実装 | 期待する検出ラベル |
| --- | --- | --- |
| 1 | 最大レイテンシを更新しない | PERF_LATENCY |
| 2 | 未完了でない応答を記録しない | PERF_ERROR |
| 3 | `start`で窓の完了数をクリアしない | PERF_WINDOW |
| 4 | 応答後も未完了スロットを解放しない | PERF_COUNT |

変異4は`req_ready`と未完了数の不一致で検出します。負の試験の観測は通常の13目標へ加算しません。

## 実行

```sh
python3 examples/local-performance-monitor/run.py --out artifacts/perf-monitor
python3 examples/local-performance-monitor/run.py --profile nightly --out artifacts/perf-nightly
python3 -m unittest discover -s examples/local-performance-monitor/tests -v
```

smokeは200操作×1 seed、nightlyは1000操作×3 seedを固定シナリオへ加えます。各構成7／9件、全体14／18件のJUnitで、確認テストは5件です。

## 確認範囲

2026-10-28にPython 3.14.7、Icarus Verilog 14.0開発版で両構成のsmoke／nightly、13目標、4変異、確認5件が成功しました。

レイテンシはシミュレーションのクロックサイクルであり、実周波数での時間や帯域を保証しません。最大値は8ビットで、長時間の回帰では飽和・折返しを別に扱う必要があります。バスの帯域制限、仲裁、QoS、クロック周波数、STA、シリコン実測は対象外です。
