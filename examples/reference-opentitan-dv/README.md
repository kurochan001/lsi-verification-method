# OpenTitanのDV環境の参照例

UART IPを入口に、検証計画、共通環境、RAL、比較、カバレッジ、実行設定を読む例です。[外部環境の比較](../../docs/method/open-source-dv-environments.md)も参照してください。ここは**読解と手動演習の参照例**で、統合nightlyでOpenTitanのIP／SoCをシミュレーションするランナーではありません。

## 参照する版

- リポジトリ：[lowRISC/opentitan](https://github.com/lowRISC/opentitan)
- 固定コミット：[`0f8469f729ce8e84993c9987f90af3589172c79d`](https://github.com/lowRISC/opentitan/tree/0f8469f729ce8e84993c9987f90af3589172c79d)
- 上流の案内：[DVの準備](https://opentitan.org/book/doc/getting_started/setup_dv.html)、[検証方法論](https://opentitan.org/book/doc/contributing/dv/methodology/index.html)

## UARTから共通基盤を読む

| 読む順序 | 固定版のファイル | 確認すること |
| --- | --- | --- |
| 1. 計画 | [uart_testplan.hjson](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/hw/ip/uart/data/uart_testplan.hjson) | smoke、パリティ、FIFO、割り込み等のtestpointと対応テスト |
| 2. 実行設定 | [uart_sim_cfg.hjson](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/hw/ip/uart/dv/uart_sim_cfg.hjson) | `uart_smoke`とsequence、共通設定・CSR試験等のimport |
| 3. 環境 | [uart_env.sv](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/hw/ip/uart/dv/env/uart_env.sv) | `cip_base_env`の継承、agent、`en_scb`時の接続、virtual sequencer |
| 4. 比較と到達 | [uart_scoreboard.sv](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/hw/ip/uart/dv/env/uart_scoreboard.sv)、[uart_env_cov.sv](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/hw/ip/uart/dv/env/uart_env_cov.sv) | バス／UARTの観測、期待値、機能カバレッジの収集 |
| 5. 共通部分 | [cip_base_env.sv](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/hw/dv/sv/cip_lib/cip_base_env.sv) | RALや共通機構をIP固有の処理と分ける |

例えば計画上の`smoke`と、実行名`uart_smoke`と、`uart_smoke_vseq`は別の識別子です。記述・選択・実装・観測を結び付け、名前が似ているだけで対応済みと判断しません。[APB＋UARTの教材](../local-apb-uart/README.md)から進むと、レジスター・データ経路・割り込みの責務を追いやすくなります。

## フルDVとソフトウェア実行の経路

上流のDV手順にある実行形は次のとおりです。これは**今回実行していないIP UVMの例**で、必要なシミュレーターとライセンス、依存・生成・共通基盤の準備を前提にします。

```text
dvsim hw/ip/uart/dv/uart_sim_cfg.hjson -i uart_smoke --fixed-seed=1
```

固定版の[pyproject.toml](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/pyproject.toml)はDVSim 1.52.0を依存として指定しています。旧配置の`util/dvsim/dvsim.py`を想定せず、利用版の導入方法を確認します。Verilatorでソフトウェアを実行する経路も、上のIP UVMと分けて選びます。

## 商用ツールを使わない小演習

実際の上流[計画操作CLI](https://github.com/lowRISC/opentitan/blob/0f8469f729ce8e84993c9987f90af3589172c79d/util/testplantool/README.md)を使います。独自の3 testpointのCSV出力・条件照会と、出力内容の自動照合を行います。**RTL・UVM・ISSは実行せず、testpoint数を試験合格数やカバレッジへ数えません。**

Python 3.13.15・macOS arm64で確認しました。以下は本リポジトリのルートから、同じシェルで順に実行します。`DV_TOUR_PYTHON`でPythonの実行ファイル、`DV_TOUR_DIR`で新しい出力先を指定できます。末尾の照合に標準ライブラリーの`tomllib`を使うため、この手順にはPython 3.11〜3.13が必要です。

### 1. 固定版と専用のPython環境を用意する

```sh
set -e
dv_tour_dir="${DV_TOUR_DIR:-$PWD/artifacts/opentitan-testplan-tour}"
dv_tour_python="${DV_TOUR_PYTHON:-python3.13}"
test ! -e "$dv_tour_dir"
mkdir -p "$dv_tour_dir"
"$dv_tour_python" -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14)'
git clone --depth 1 --filter=blob:none --sparse https://github.com/lowRISC/opentitan.git "$dv_tour_dir/opentitan"
git -C "$dv_tour_dir/opentitan" fetch --depth 1 origin 0f8469f729ce8e84993c9987f90af3589172c79d
git -C "$dv_tour_dir/opentitan" checkout --detach 0f8469f729ce8e84993c9987f90af3589172c79d
git -C "$dv_tour_dir/opentitan" sparse-checkout set util/testplantool
"$dv_tour_python" -m venv "$dv_tour_dir/python"
dv_tour_py="$dv_tour_dir/python/bin/python"
"$dv_tour_py" -m pip install --disable-pip-version-check --only-binary=:all: \
  --report "$dv_tour_dir/python-install.json" \
  click==8.4.2 hjson==3.1.0 mako==1.3.12 markupsafe==3.0.3
dv_tour_cli="$dv_tour_dir/opentitan/util/testplantool/testplantool.py"
"$dv_tour_py" "$dv_tour_cli" --help > "$dv_tour_dir/help.log"
```

小演習用の依存だけを隔離して導入します。OpenTitan全体のPython・RTL・ソフトウェアの実行環境を導入する手順ではありません。

### 2. 計画のimport・CSV・条件照会を試す

```sh
"$dv_tour_py" - "$dv_tour_dir" <<'PY'
import json
import sys
from pathlib import Path
b = Path(sys.argv[1]) / 'fixture'
b.mkdir()
(b / 'MODULE.bazel').write_text('')
def point(name, stage, states):
    return dict(name=name, desc='Tutorial metadata only; not an executed RTL test',
                stage=stage, si_stage='SV1' if stage == 'V1' else 'SV2',
                lc_states=states, tests=['tutorial_' + name],
                bazel=['//example:' + name + '_test'])
top = dict(name='tutorial_top', import_testplans=['child.hjson'], testpoints=[
    point('reset', 'V1', ['DEV', 'PROD']), point('irq', 'V2', ['DEV'])])
child = dict(name='tutorial_ip', import_testplans=[], testpoints=[
    point('bus_error', 'V1', ['DEV'])])
for name, data in [('top', top), ('child', child)]:
    (b / (name + '.hjson')).write_text(json.dumps(data, indent=2) + '\n')
PY
"$dv_tour_py" "$dv_tour_cli" export-csv "$dv_tour_dir/fixture/top.hjson" "$dv_tour_dir/plan.csv" > "$dv_tour_dir/export.log"
"$dv_tour_py" "$dv_tour_cli" query "$dv_tour_dir/fixture/top.hjson" \
  --stage '^V1$' --lc-state '^DEV$' --fields name,bazel > "$dv_tour_dir/selected.hjson"
"$dv_tour_py" "$dv_tour_cli" query "$dv_tour_dir/fixture/top.hjson" \
  --name '^irq$' --fields si_stage > "$dv_tour_dir/field-before.hjson"
```

`MODULE.bazel`は、この独自の入力のimport基準をツールへ示すための目印です。Bazelのテストを実行するものではありません。CSVには3点、V1かつDEVの照会には`reset`と`bus_error`の2点が出ます。`stage`と`si_stage`は別のメタデータです。

### 3. フィールド選択の不具合を再現し、比較用コピーで修正する

確認版の`--fields si_stage`は終了コード0でも、`stage`と`si_stage`の両方を返します。CLIが文字列をそのままリスト用のAPIへ渡すため、`stage in "si_stage"`が真になることが原因です。ここでは上流のチェックアウトを変更せず、コピーで引数をリストへ変換します。

```sh
"$dv_tour_py" - "$dv_tour_dir" <<'PY'
import shutil
import sys
from pathlib import Path
b = Path(sys.argv[1])
repo = b / 'opentitan'
fixed = b / 'testplantool-fixed'
shutil.copytree(repo / 'util/testplantool', fixed,
                ignore=shutil.ignore_patterns('__pycache__'))
for name in ('LICENSE', 'NOTICE'):
    shutil.copyfile(repo / name, fixed / name)
p = fixed / 'cli.py'
text = p.read_text()
needle = '    tp = Testplan.from_top(Path(input_file))\n    tp = tp.filter_testpoints('
replacement = ('    selected_fields = None if fields is None else [f.strip() for f in fields.split(",")]\n'
               + needle)
assert text.count(needle) == 1
assert text.count('    ).filter_fields(fields)') == 1
text = text.replace(needle, replacement, 1)
text = text.replace('    ).filter_fields(fields)', '    ).filter_fields(selected_fields)')
p.write_text(text)
PY
"$dv_tour_py" "$dv_tour_dir/testplantool-fixed/testplantool.py" query \
  "$dv_tour_dir/fixture/top.hjson" --name '^irq$' --fields si_stage > "$dv_tour_dir/field-after.hjson"
"$dv_tour_py" - "$dv_tour_dir" <<'PY'
import csv
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path
import hjson
b = Path(sys.argv[1])
with (b / 'plan.csv').open() as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 3 and {r['name'] for r in rows} == {'reset', 'irq', 'bus_error'}
assert {r['ip'] for r in rows} == {'tutorial_top', 'tutorial_ip'}
selected = hjson.loads((b / 'selected.hjson').read_text())
assert {r['name'] for r in selected} == {'reset', 'bus_error'}
assert all(set(r) == {'name', 'bazel'} for r in selected)
before = hjson.loads((b / 'field-before.hjson').read_text())
after = hjson.loads((b / 'field-after.hjson').read_text())
assert before == [dict(stage='V2', si_stage='SV2')]
assert after == [dict(si_stage='SV2')]
repo = b / 'opentitan'
commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
assert commit == '0f8469f729ce8e84993c9987f90af3589172c79d'
lock = tomllib.loads((repo / 'uv.lock').read_text())
packages = {p['name']: p for p in lock['package'] if 'version' in p}
install = json.loads((b / 'python-install.json').read_text())
for row in install['install']:
    p = packages[row['metadata']['name'].lower()]
    assert p['version'] == row['metadata']['version']
    allowed = {w['hash'] for w in p.get('wheels', [])}
    if 'sdist' in p:
        allowed.add(p['sdist']['hash'])
    assert 'sha256:' + row['download_info']['archive_info']['hashes']['sha256'] in allowed
paths = ['opentitan/util/testplantool/cli.py', 'testplantool-fixed/cli.py']
hashes = {p: hashlib.sha256((b / p).read_bytes()).hexdigest() for p in paths}
assert hashes[paths[0]] == '10f93df5d698778e86f529ca34ddad34f7dc56c37852b744d2c716136fee51d6'
assert hashes[paths[1]] == 'c25904043ed05275c458a52ddb1e471b7c5e6c1350f86490fb9794bdd0c07079'
summary = dict(success=True, upstream_commit=commit, csv_rows=3, selected_rows=2,
               field_bug_reproduced=True, field_fix_verified=True, source_sha256=hashes,
               scope='Metadata CLI only; no RTL, UVM, ISS or chip simulation')
(b / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
PY
```

最後の照合は、点数だけでなく名前・import元・選択フィールド、修正前後の結果、取得版、CLIのハッシュ、依存パッケージと上流`uv.lock`のダウンロードハッシュを確認します。

コピーには上流の著作権表示とLICENSE・NOTICEを保持します。上流由来の修正例の対象はApache-2.0で、本リポジトリのLLVM例外を追加するものではありません。修正を上流へ送付・反映した結果ではありません。

## 確認したこと・実行していないこと

固定版の取得、UARTの計画とコードの読解、上記の計画ツールの小演習を確認しました。独自testpointの抽出結果と、実際の試験結果・機能カバレッジ・OpenTitanの検証段階は分けて扱います。

IP／SoCのフルUVM、Verilatorでのソフトウェア実行、カバレッジ収束・サインオフは今回未実行です。統合nightlyの130登録項目・108ルートジョブにも加算していません。
