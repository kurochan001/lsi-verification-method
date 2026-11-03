# LiteDRAMのメモリー制御・ECC検証環境の参照例

DRAMコントローラーを、リフレッシュ、バンク制御、AXI等のフロントエンド、ECC、PHYの層に分けて読む例です。Python／Migenのシミュレーションとunittestによる判定を学べます。[公開DV環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。

## 参照する版

| 対象 | 固定コミット |
| --- | --- |
| LiteDRAM | [enjoy-digital/litedram / `c048f40e4aa305527b50dee0d96f88d7d20a5cc6`](https://github.com/enjoy-digital/litedram/tree/c048f40e4aa305527b50dee0d96f88d7d20a5cc6) |
| 小演習のLiteX | [enjoy-digital/litex / `4cfda8a561d2878331ba14b37c09d4f7601c77de`](https://github.com/enjoy-digital/litex/tree/4cfda8a561d2878331ba14b37c09d4f7601c77de) |
| 小演習のMigen | [m-labs/migen / `e19524c963a8342952840983047557707fbe0b6a`](https://github.com/m-labs/migen/tree/e19524c963a8342952840983047557707fbe0b6a) |

2026-11-03に取得した固定版です。下記の限定した演習で3つのソース版を組み合わせて確認しました。

## 読む順序

| ソース | 学ぶこと |
| --- | --- |
| [test/test_refresh.py](https://github.com/enjoy-digital/litedram/blob/c048f40e4aa305527b50dee0d96f88d7d20a5cc6/test/test_refresh.py) | 周期タイマー、コマンド列、延期回数、ZQCSとの関係をサイクル単位で比較 |
| [test/test_ecc.py](https://github.com/enjoy-digital/litedram/blob/c048f40e4aa305527b50dee0d96f88d7d20a5cc6/test/test_ecc.py) | 正常の符号化・復号、1 bit訂正、2 bit誤り検出、エラーカウンター、部分書込み |
| [test/test_axi.py](https://github.com/enjoy-digital/litedram/blob/c048f40e4aa305527b50dee0d96f88d7d20a5cc6/test/test_axi.py)、[test/common.py](https://github.com/enjoy-digital/litedram/blob/c048f40e4aa305527b50dee0d96f88d7d20a5cc6/test/common.py) | バースト・ID・last、チャネルの待ち、メモリーモデル、データ比較と時間上限 |
| [.github/workflows/ci.yml](https://github.com/enjoy-digital/litedram/blob/c048f40e4aa305527b50dee0d96f88d7d20a5cc6/.github/workflows/ci.yml) | 軽量なPython試験と、ツールチェーン等を含む全体試験の分割・定期実行 |

Pythonで記述された回路をMigenでシミュレーションする経路です。Verilogへ生成したRTLの外部シミュレーション、実DRAMや基板の信号品質・初期化・トレーニングの評価と、結果を分けます。

## 外部HDLシミュレーターを使わない小演習

リポジトリのルートから、新しい出力先を使います。Git・Python 3・venv・ネットワークが必要です。確認環境はPython 3.13.15・macOS arm64です。3つのソース版を固定し、追加Pythonパッケージの解決結果はpipのreportとfreezeへ保存します。全推移依存を固定したlock環境ではありません。

```sh
set -eu
litedram_work="$PWD/artifacts/upstream-litedram"
mkdir -p "$litedram_work"
git clone --no-checkout https://github.com/enjoy-digital/litedram.git "$litedram_work/litedram"
git -C "$litedram_work/litedram" checkout --detach c048f40e4aa305527b50dee0d96f88d7d20a5cc6
git clone --no-checkout https://github.com/enjoy-digital/litex.git "$litedram_work/litex"
git -C "$litedram_work/litex" checkout --detach 4cfda8a561d2878331ba14b37c09d4f7601c77de
git clone --no-checkout https://github.com/m-labs/migen.git "$litedram_work/migen"
git -C "$litedram_work/migen" checkout --detach e19524c963a8342952840983047557707fbe0b6a
python3 -m venv "$litedram_work/python"
"$litedram_work/python/bin/python" -m pip install --report "$litedram_work/install.json" \
  "$litedram_work/migen" "$litedram_work/litex" "$litedram_work/litedram"
"$litedram_work/python/bin/python" -m pip freeze > "$litedram_work/packages.txt"
cd "$litedram_work/litedram"
```

続けて、リフレッシュ3テストと、ECCの正常・1 bit訂正・2 bit誤り検出を実行します。通常のPython設定を使い、子プロセスの失敗・120秒の時間超過を失敗として伝えます。

```sh
../python/bin/python - <<'PY'
import subprocess
import sys

if sys.flags.optimize:
    raise RuntimeError("Use Python without -O, -OO, or PYTHONOPTIMIZE")
subprocess.run([
    sys.executable, "-m", "unittest", "-v",
    "test.test_refresh",
    "test.test_ecc.TestECC.test_ecc_32_7",
    "test.test_ecc.TestECC.test_ecc_sec_errors",
    "test.test_ecc.TestECC.test_ecc_ded_errors",
], check=True, timeout=120)
PY
```

確認版は`Ran 6 tests`・`OK`で終了しました。リフレッシュの1テスト内で周期1〜31、別の1テスト内で延期1・2・4・8を調べますが、これを追加の独立テスト件数へ加算しません。ECCは期待データと訂正・検出カウンターを照合し、2 bit誤りのケースでは「データを訂正できないが検出する」という合格条件を確認します。

## ライセンス・確認範囲

主な配布条件は[BSD 2-Clause](https://github.com/enjoy-digital/litedram/blob/c048f40e4aa305527b50dee0d96f88d7d20a5cc6/LICENSE)です。LiteX・Migen・各ファイルと追加依存の表示も保持します。上流コードはGit管理下へ複製しません。

今回の新規実行は、上記6テストのMigenシミュレーションです。AXIテスト、全テスト、生成Verilogの照合、PHY・実DRAM・FPGA動作、全構成のカバレッジ収束は未確認です。この手動演習と参照例を統合nightlyの登録数へ加算しません。[実行記録](../../PROVENANCE.md#noncpu-dv-20261103)も参照してください。
