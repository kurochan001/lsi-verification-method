# PicoRV32の参照例とIcarusによる小演習

小さなCPUのネイティブメモリーインターフェース、簡単なプログラム、実際の受付・データ比較・終了判定を読む例です。[外部DVの比較](../../docs/method/open-source-dv-environments.md)から、Ibex・CV32系・CVA6の大きな環境へ進む前の入口として使えます。

## 参照する版と読む順序

- リポジトリ：[YosysHQ/picorv32](https://github.com/YosysHQ/picorv32)
- 固定コミット：[`ef203c2b0a3fb793280f5114941416c425c5b461`](https://github.com/YosysHQ/picorv32/tree/ef203c2b0a3fb793280f5114941416c425c5b461)
- 2026-11-03に確認したGitHubの状態はarchivedです。ここでは固定版を学習用に参照します。

| ファイル | 読むポイント |
| --- | --- |
| [README.md](https://github.com/YosysHQ/picorv32/blob/ef203c2b0a3fb793280f5114941416c425c5b461/README.md) | ネイティブ・AXI4-Lite・Wishboneの各経路、PCPI、構成と試験の違い |
| [picorv32.v](https://github.com/YosysHQ/picorv32/blob/ef203c2b0a3fb793280f5114941416c425c5b461/picorv32.v) | 選んだトップのポートと構成、要求・応答・trap |
| [testbench_ez.v](https://github.com/YosysHQ/picorv32/blob/ef203c2b0a3fb793280f5114941416c425c5b461/testbench_ez.v) | 外部ファームウェア不要の6命令、RAM応答、1020番地の値を増やすループ |
| [Makefile](https://github.com/YosysHQ/picorv32/blob/ef203c2b0a3fb793280f5114941416c425c5b461/Makefile) | `test_ez`と、外部ツールチェーン・ファームウェアを使う別のtest群 |

## 小演習：表示を自動判定へつなぐ

上流の`test_ez`は簡単な実行表示の例で、1000サイクル経過すると終了します。終了コード0だけでは、表示されたデータが期待どおりかまで確認できません。

この演習では上流のCPUを変更せず、TBのコピーに監視モジュールとタイムアウトの判定を追加します。受理したデータ転送を数え、全バイト有効のstoreが0〜7の8回、対応するloadが7回という順序・値を確認して成功にします。受理前の提示や命令fetchはこのデータ件数へ加算しません。

| 実行 | TBのコピーへ与える条件 | 期待する判定 |
| --- | --- | --- |
| 正常 | 1ずつ増やすプログラムと通常のメモリー応答 | store 8回・load 7回の値と順序が一致し、`PICOTOUR_PASS` |
| 増分誤り | プログラムの増分を2へ変更 | `PICOTOUR_DATA`を検出して失敗 |
| 応答停止 | メモリー応答を停止 | `PICOTOUR_TIMEOUT`を検出して失敗 |

下のPythonは、負例が予定した理由で失敗したことも確認します。ビルド失敗や無関係な異常終了を、対照確認の成功として採用しません。

Python 3.10以上、Git、make、Icarusの`iverilog`・`vvp`をPATHへ準備し、本リポジトリのルートから同じシェルで実行します。追加PythonパッケージとRISC-Vコンパイラーは使いません。掲載手順はPython 3.13.15・macOS arm64・Icarus Verilog 14系で確認しました。

### 1. 固定版を新しい出力先へ取得する

```sh
set -e
pico_tour_dir="${PICO_TOUR_DIR:-$PWD/artifacts/picorv32-tour}"
test ! -e "$pico_tour_dir"
mkdir -p "$pico_tour_dir"
git clone --depth 1 --sparse https://github.com/YosysHQ/picorv32.git "$pico_tour_dir/picorv32"
git -C "$pico_tour_dir/picorv32" fetch --depth 1 origin ef203c2b0a3fb793280f5114941416c425c5b461
git -C "$pico_tour_dir/picorv32" checkout --detach ef203c2b0a3fb793280f5114941416c425c5b461
```

### 2. 上流の簡易TBを実行する

```sh
make -C "$pico_tour_dir/picorv32" test_ez > "$pico_tour_dir/native-ez.log" 2>&1
```

元の実行表示をログへ保存します。このコマンドが終了したことと、次の独立したデータ比較を区別します。

### 3. 正常・異なるプログラム・応答停止を照合する

```sh
"${PICO_TOUR_PYTHON:-python3}" - "$pico_tour_dir" <<'PY'
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

base = Path(sys.argv[1]).resolve()
repo = base / 'picorv32'
out = base / 'checked'
out.mkdir()
pin = 'ef203c2b0a3fb793280f5114941416c425c5b461'
require(subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == pin,
        'upstream commit differs')
iverilog, vvp = shutil.which('iverilog'), shutil.which('vvp')
require(iverilog and vvp, 'Icarus tools not found')
original = (repo / 'testbench_ez.v').read_text()
require(original.count('$finish;') == 1, 'unexpected TB finish pattern')
checked = original.replace('$finish;', '$fatal(1, "PICOTOUR_TIMEOUT");')
monitor = '''`timescale 1ns/1ps
module tutorial_checks;
  integer stores = 0, loads = 0;
  always @(posedge testbench.clk) if (testbench.resetn) begin
    if (testbench.trap !== 1'b0) $fatal(1, "PICOTOUR_TRAP");
    if (testbench.mem_valid && testbench.mem_ready && !testbench.mem_instr) begin
      if (testbench.mem_addr !== 32'd1020) $fatal(1, "PICOTOUR_ADDRESS");
      if (testbench.mem_wstrb !== 4'b0000) begin
        if (testbench.mem_wstrb !== 4'hf || testbench.mem_wdata !== stores || stores != loads)
          $fatal(1, "PICOTOUR_DATA stores=%0d actual=%h", stores, testbench.mem_wdata);
        stores = stores + 1;
        if (stores == 8) begin
          if (loads != 7) $fatal(1, "PICOTOUR_COUNT");
          $display("PICOTOUR_PASS stores=8 loads=7");
          $finish;
        end
      end else begin
        if (stores != loads + 1 || testbench.mem_rdata !== (stores - 1))
          $fatal(1, "PICOTOUR_LOAD");
        loads = loads + 1;
      end
    end
  end
endmodule
'''
require(checked.count("32'h 00110113") == 1, 'unexpected increment instruction')
require(checked.count('mem_ready <= 1;') == 1, 'unexpected memory response pattern')
variants = [
    ('normal', checked, 0, 'PICOTOUR_PASS stores=8 loads=7'),
    ('wrong-program', checked.replace("32'h 00110113", "32'h 00210113"), 1, 'PICOTOUR_DATA'),
    ('no-response', checked.replace('mem_ready <= 1;', 'mem_ready <= 0;'), 1, 'PICOTOUR_TIMEOUT'),
]
results = []
for name, tb, expected_failure, label in variants:
    d = out / name
    d.mkdir()
    (d / 'testbench.v').write_text(tb)
    (d / 'monitor.sv').write_text(monitor)
    build = [iverilog, '-g2012', '-s', 'testbench', '-s', 'tutorial_checks',
             '-o', str(d / 'sim.vvp'), str(repo / 'picorv32.v'),
             str(d / 'testbench.v'), str(d / 'monitor.sv')]
    compiled = subprocess.run(build, cwd=d, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=30)
    (d / 'build.log').write_text(compiled.stdout)
    require(compiled.returncode == 0, f'{name}: build failed: {compiled.stdout}')
    command = [vvp, '-N', str(d / 'sim.vvp')]
    run = subprocess.run(command, cwd=d, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=30)
    (d / 'simulation.log').write_text(run.stdout)
    require(label in run.stdout, f'{name}: missing expected label {label}')
    require((run.returncode != 0) == bool(expected_failure),
            f'{name}: unexpected simulation returncode {run.returncode}')
    if expected_failure:
        require('PICOTOUR_PASS' not in run.stdout, f'{name}: false success in negative control')
    else:
        require(run.stdout.count(label) == 1 and 'FATAL' not in run.stdout,
                f'{name}: invalid normal completion')
    results.append(dict(case=name, expected_label=label, returncode=run.returncode,
                        build_command=build, command=command))
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
source_hashes = {p: sha(repo / p) for p in ['picorv32.v', 'testbench_ez.v', 'Makefile', 'COPYING']}
for tool in [iverilog, vvp]:
    version = subprocess.run([tool, '-V'], text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=10)
    (out / (Path(tool).name + '-version.log')).write_text(version.stdout)
require((repo / 'testbench_ez.v').read_text() == original, 'upstream TB changed')
require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True),
        'upstream worktree changed')
summary = dict(success=True, upstream_commit=pin, python=sys.version,
               source_sha256=source_hashes, stores=8, loads=7, checked_cases=results,
               scope='Native-bus increment program only; no full ISA, ISS, UVM or formal proof')
(base / 'pico-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(dict(success=True, checked_cases=3, stores=8, loads=7)))
PY
```

正常ケースは、値・順序・件数を満たした場合にだけ`PICOTOUR_PASS stores=8 loads=7`で終了します。trapやデータ相違は失敗にします。次の2件は判定処理を確かめる負例です。

- **wrong-program**：加算を+1から+2へ変えたプログラムを使い、`PICOTOUR_DATA`・非0終了・成功表示なしを要求します。CPUのRTL変異や未知の不具合の検出としては数えません。
- **no-response**：メモリー応答を止め、`PICOTOUR_TIMEOUT`・非0終了・成功表示なしを要求します。環境の応答停止をCPUの機能不具合と断定するものではありません。

ビルド不能やPython側の時間切れは、予定した負例の成功へ変えません。各ケースのビルド・実行ログ、コマンド、ツール版、上流ファイルのSHA-256、固定コミットと3判定を保存します。既存の出力先を上書きせず、元のGitチェックアウトのクリーンさも確認します。

Python側の合否は明示的な条件分岐で検査します。Pythonの`assert`文は`-O`や`PYTHONOPTIMIZE`で無効になるため、ビルド失敗や結果欠落を拒否する運用上の判定には使いません。

## 確認範囲と次に進む例

これはネイティブバス上の小さな増分プログラムを使う手動演習です。全ISA、IRQ、PCPI、AXI4-Lite／Wishbone、ISSとの比較、フォーマル証明、カバレッジ収束は今回実行していません。UVMのフルDVを確認した結果とも区別します。

CPU本体の[COPYING](https://github.com/YosysHQ/picorv32/blob/ef203c2b0a3fb793280f5114941416c425c5b461/COPYING)と、簡易TB先頭のpublic domain表示はそのまま保持します。上流ソース・生成したバイナリーを本リポジトリのGit管理へ取り込まず、統合nightlyの130登録項目・108ルートジョブへも加算しません。

[小規模RISC-VのISS比較](../local-riscv-iss/README.md)、[CV32系](../reference-core-v-verif/README.md)、[目視確認のアサーション化](../../docs/method/assertion-based-regression.md)へ進み、より広い要求・構成・合否条件を追加します。
