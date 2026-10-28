# JTAG TAP・IDCODE・BYPASS・境界走査を検証する

IEEE 1149.1のTAP状態遷移、命令レジスタ（IR）、IDCODE、BYPASS、SAMPLE/PRELOAD、EXTESTを小さな回路で確認する教材です。TCKの立上りで状態を更新し、立下りでTDOを更新します。IR/DRのLSB先行シフト、Updateのタイミング、境界走査レジスタからピンへの駆動を分けて判定します。

## TAPとデータレジスタ

```mermaid
flowchart LR
  accTitle: TAPの状態とIR/DR
  accDescr: TMSで16状態を遷移し、IRでIDCODE・BYPASS・境界走査レジスタを選ぶ。
  T["TCK・TMS"] --> F["16状態のTAP FSM"]
  F --> I["IRシフト・更新"]
  F --> D["DRキャプチャ・シフト・更新"]
  I --> M{"IR"}
  M --> ID["IDCODE 32bit"]
  M --> BP["BYPASS 1bit"]
  M --> BS["境界走査 8bit"]
  BS --> P["pin_out"]
  PI["pin_in"] --> BS
  D --> O["TDO"]
  ID --> O
  BP --> O
```

図は教材で実装した命令とデータレジスタの関係です。実デバイスの全命令・全ビット長を再現したものではありません。

## 仕様

| 命令 | IR | DR | 動作 |
| --- | --- | --- | --- |
| IDCODE | 0001 | 32ビット | リセット後の既定命令。IDCODEをLSB先行で読み出す |
| BYPASS | 1111 | 1ビット | 1ビット遅延 |
| SAMPLE/PRELOAD | 0010 | 8ビット | Captureで`pin_in`を取り込み、シフトする |
| EXTEST | 0011 | 8ビット | Capture/Shift後、Updateで`pin_out`へ駆動 |

- TAPは16状態を持ち、TMSで遷移します。Test-Logic-ResetではIRをIDCODEへ戻します。
- Capture-IRは`0001`をロードし、Shift-IRはLSB先行で4ビットをシフトします。Update-IRでIRを更新します。
- Capture-DRは命令に応じてIDCODE・BYPASS・境界走査レジスタをロードします。Shift-DRはLSB先行です。
- Update-DRはEXTESTなら境界走査レジスタを`pin_out`へ駆動し、それ以外は`pin_in`を出力します。
- `trst_n`は非同期リセットです。TDOはシフト状態以外では0です。
- TDOはTCKの立下りで更新し、テストベンチは立上り前の値を比較します。

## 独立した期待値と構成

Pythonは16状態の遷移表、IR/DRのシフト、Updateの効果をRTLと別に実装します。TDOだけでなく、内部の状態番号とIRも比較するため、シフト方向やUpdate位置の誤りを分離できます。

| 構成 | IDCODE |
| --- | --- |
| `id12345678` | 0x12345678 |
| `iddeadbeef` | 0xDEADBEEF |

[要求カタログ](requirements.json)は3要求・12目標です。固定シナリオはIDCODEの32ビット読出し、BYPASS、SAMPLEのCapture、EXTESTの8ビット駆動、Pause/Exit2を通る経路、IRの連続更新、リセット復帰を含みます。

## 意図的な誤実装

| 番号 | 誤実装 | 期待する検出ラベル |
| --- | --- | --- |
| 1 | IDCODEの1ビットを反転 | JTAG_TDO |
| 2 | Update-IRでIRを誤る | JTAG_IR |
| 3 | EXTESTのUpdateでpin_outを駆動しない | JTAG_BOUNDARY |
| 4 | Exit2-DRからShift-DRへ戻る遷移を誤る | JTAG_STATE |

状態番号・IR・TDO・ピン出力を別々に比較するため、変異の影響を該当する判定へ対応付けられます。負の試験の観測は通常の12目標へ加算しません。

## 実行

```sh
python3 examples/local-jtag-tap/run.py --out artifacts/jtag-tap
python3 examples/local-jtag-tap/run.py --profile nightly --out artifacts/jtag-nightly
python3 -m unittest discover -s examples/local-jtag-tap/tests -v
```

smokeは8回のランダム命令・DR操作×1 seed、nightlyは20回×3 seedを固定シナリオへ加えます。各構成7／9件、全体14／18件のJUnitで、確認テストは6件です。

## 確認範囲

2026-10-28にPython 3.14.7、Icarus Verilog 14.0開発版で両構成のsmoke／nightly、12目標、4変異、確認6件が成功しました。

この教材はTAPのデジタル動作と8ビット境界走査の教材であり、IEEE 1149.1の全命令・全必須動作の適合証明ではありません。実JTAGのTCK周波数、セットアップ・ホールド、TDOの実配線遅延、BSDL、ATPG、スキャンチェーン、故障検出率、実チップのDFTは対象外です。
