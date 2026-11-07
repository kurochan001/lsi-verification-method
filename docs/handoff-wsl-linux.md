# WSLのLinuxで確認するためのハンドオフ

2026-11-07に[リポジトリ全体のレビュー](../PROVENANCE.md#repository-review-20261107)を行い、修正を`05e957f`までmainへ入れました。この時点で全例の検証を手元で通したのはmacOS arm64だけで、Linuxでの実行はGitHub ActionsのUbuntu 24.04に任せていました。この資料は、WSLのLinuxで同じ検証をやり直すための手順です。人でもClaude Codeでも、上から順に進められます。

**この手順はmacOSで書き、2026-11-07にWSL2のUbuntu 24.04で初めて実行しました。** [結果と、手順から直した箇所](../PROVENANCE.md#wsl-linux-check-20261107)を記録してあります。別の環境でやり直してずれていたら直し、直した内容も結果と一緒に記録してください。

## 確かめること

| 項目 | CIで分からない理由 |
| --- | --- |
| 手順書どおりに、空の環境から全ツールを構築できる | CIは構築結果をキャッシュから戻すことが多い |
| 文書検査、全セルフテスト、全例のsmoke・nightlyがmacOSと同じ結果になる | CIと別のLinux環境でも同じになるかを見る |
| kirimasimで80例・107構成のsmokeが合格する | CIは最新版を実行する。ここではmacOSの記録と同じ版で、OSの違いだけを比べる |

[CIの状態](#ciの状態)は別に確認します。

## 1. WSLを用意する

WSL2のUbuntu 24.04（x86-64）を使います。CIと同じ版です。固定版のOSS CAD SuiteはLinuxではx64だけなので、Arm版のWindowsでは全例を実行できません。

PowerShellで次を実行します。

```powershell
wsl --install -d Ubuntu-24.04
```

同じ名前のdistroが既にあれば、開発ツールが入っていないことを確かめて、それを使えます。開発に使っているdistroは避けます。別版のコンパイラーやVerilator、`VERILATOR_ROOT`のような環境変数が結果に影響し得るので、空の環境から構築できることも確かめられません。

Windows側のコマンドがLinuxのPATHに混ざらないよう、`/etc/wsl.conf`に次を追記します。既存の`[boot]`などは残します。PowerShellで`wsl --terminate Ubuntu-24.04`を実行してから開き直します。`wsl --shutdown`は他のdistroも止めます。

```ini
[interop]
appendWindowsPath=false
```

作業はLinux側のホームディレクトリで行います。`/mnt/c`の下では、実行ビット、シンボリックリンク、大文字・小文字の区別が変わるので、固定版の照合が失敗します。

次で確認します。

```sh
uname -m                      # x86_64
. /etc/os-release; echo "$VERSION_ID"   # 24.04
nproc; free -h; df -h ~       # 空きディスクは50GB以上を目安にする
```

ディスクの目安はWSLの実測です。終了時の使用量はOSを含めて47GBでした。内訳は、OSS CAD Suiteが3.2GB、ネイティブツールが2.9GB、kirimasimの構築が8.9GB、smokeの出力が12GB、nightlyの出力が15GB、kirimasimの出力が915MBです。再実行すると、その分が増えます。

長い実行はtmuxの中で行い、実行中はWindowsをスリープさせません。

## 2. OSのパッケージとPython・Node.jsを入れる

パッケージはCIの一覧に、Git、curl、tmuxと、kirimasimに必要な`libbz2-dev`を加えたものです。

```sh
sudo apt-get update
sudo apt-get install -y autoconf automake bison cmake flex g++ gcc gperf help2man \
  libeigen3-dev libfl-dev libtool llvm make ninja-build perl tcl-dev zlib1g-dev swig \
  git curl tmux libbz2-dev
```

全例にはPython 3.13以上、文書検査にはNode.js 22以上が必要です。Ubuntu 24.04の標準はPython 3.12とNode.js 18なので、別に入れます。Pythonは、macOSの実行でも使ったuvの配布物です。cocotbが読み込む共有ライブラリーも含まれています。

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv python install 3.13

curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source "$HOME/.nvm/nvm.sh"
nvm install 24

command -v git node npm       # どれも /mnt/c で始まらないこと
```

## 3. リポジトリを取得する

```sh
cd ~
git clone -c core.autocrlf=false https://github.com/kurochan001/lsi-verification-method.git
cd lsi-verification-method
git log -2 --oneline
```

このリポジトリには`.gitattributes`がありません。改行がCRLFに変わると、固定したハッシュと一致しなくなります。Windows側のGitで取得した作業ツリーは使わないでください。

macOSの`artifacts/`は持ってきません。Git管理外で、ツールも証跡もmacOS用です。

## 4. ツールを構築する

CIの`Prepare and diagnose full environment`までと同じ手順です。[環境の準備](../tools/ENVIRONMENT.md)に説明があります。`--out`は毎回新しい場所を指定します。失敗したら別の`--out`でやり直します。

```sh
PY="$(uv python find 3.13)"
J=2     # 初回はCIと同じ2並列にする

"$PY" tools/build_native.py --profile full --jobs "$J" --out artifacts/toolchains/native
"$PY" tools/setup_oss_cad.py --out artifacts/toolchains/oss
"$PY" tools/setup_ngspice.py --jobs "$J" --out artifacts/toolchains/ngspice
"$PY" tools/setup_environment.py --profile full \
  --tool-bin "$PWD/artifacts/toolchains/native/install/bin" \
  --oss-home "$PWD/artifacts/toolchains/oss/oss-cad-suite" \
  --ngspice-home "$PWD/artifacts/toolchains/ngspice/install" \
  --out artifacts/toolchains/full

artifacts/toolchains/full/python/bin/cocotb-config --libpython   # libpythonのパスが出ること
```

ネイティブツールの構築は、WSL（32論理CPU、2並列）で約10分でした。Verilator、OpenSTA、SystemCをソースから構築するので、マシンによってはさらにかかります。各段階の上限は既定で1800秒です。足りなければ`--timeout`で延ばします。

環境の診断が合格しても、回路の検証が合格したことにはなりません。

OSS CAD Suiteに同梱のPythonを直接起動しないでください。`.pyc`が増えて固定版の照合が失敗します。レビュー中に一度起きました。心配なときは`"$PY" tools/setup_oss_cad.py --check artifacts/toolchains/oss/oss-cad-suite`で確かめられます。

## 5. 検証を実行する

先頭の変数は、この節と次の節のコマンドすべてで使います。新しいシェルを開いたときは定義し直します。

```sh
J=2
T="$PWD/artifacts/toolchains"
R="$PWD/artifacts/wsl-check"     # 再実行するときは別の名前にする
PYF="$T/full/python/bin/python"
ARGS=(--job-timeout 10800 --command-timeout 60 --formal-timeout 1800
      --child-timeout 7200 --build-timeout 600
      --python "$PYF" --formal-python "$T/full/formal/bin/python"
      --rdl-python "$PYF" --cocotb-python "$PYF"
      --uvm-home "$T/full/uvm/1800.2-2020.3.2"
      --oss-home "$T/oss/oss-cad-suite"
      --tool-bin "$T/native/install/bin"
      --tool-bin "$T/full/formal/bin"
      --tool-bin "$T/ngspice/install/bin")

# 文書検査
"$PYF" tools/check_docs.py --out "$R/docs"

# 全セルフテスト。PATHの変更はこのコマンドだけに留める
( export PATH="$T/native/install/bin:$T/full/formal/bin:$T/ngspice/install/bin:$PATH"
  export COCOTB_PYTHON="$PYF"
  "$PYF" tools/run_selftests.py --jobs "$J" --timeout 600 --out "$R/selftests" )

# 全例。先にツールだけを確認する
"$PYF" tools/run_regression.py --profile nightly --check-tools "${ARGS[@]}" --out "$R/preflight"
"$PYF" tools/run_regression.py --profile smoke --jobs "$J" "${ARGS[@]}" --out "$R/smoke"
"$PYF" tools/run_regression.py --profile nightly --jobs "$J" "${ARGS[@]}" --out "$R/nightly"

# 保存した結果を監査する
"$PYF" tools/regression_report.py --plan "$R/smoke/manifest.json" --campaign "$R/smoke" --out "$R/smoke-report"
"$PYF" tools/regression_report.py --plan "$R/nightly/manifest.json" --campaign "$R/nightly" --out "$R/nightly-report"
```

kirimasimは、macOSで使ったものと同じコミットから構築します。初回の`cmake`は、固定版のslangなどを取得します。

```sh
git clone https://github.com/kurochan001/kirimasim.git ~/kirimasim
git -C ~/kirimasim checkout d73d8922dfa20e19ccb9411adbe42a6d258bb49d
( cd ~/kirimasim && cmake --preset dev && cmake --build --preset dev )

"$PYF" tools/run_kirimasim_examples.py \
  --kirimasim ~/kirimasim/build/dev/src/driver/kirimasim \
  --profile smoke --seed 17 --jobs "$J" \
  --command-timeout 60 --job-timeout 900 --out "$R/kirimasim"
```

時間はマシンで大きく変わります。WSL（32論理CPU、2並列）ではセルフテストが約2分、smokeが約18分、nightlyが約21分、kirimasimの構築が約3分、実行が約12分でした。CIの2並列ではセルフテストが約4分、nightlyが約49分でした（2026-11-05、今回の修正の前）。macOSでは、全例を6並列で実行してsmokeが約6分、nightlyが約7分で、セルフテストが約1分、kirimasimが約3分でした。

## 6. 結果を読む

```sh
"$PYF" - "$R" <<'PY'
import json, sys
from pathlib import Path
load = lambda name: json.loads((Path(sys.argv[1]) / name).read_text())
for name in ('docs', 'selftests', 'smoke', 'nightly'):
    s = load(name + '/summary.json')
    print(name, 'success', s['success'], 'complete', s['complete'],
          sum(r.get('success', r.get('status') == 'pass') for r in s['results']), '/', s['planned'])
t = load('selftests/tests.json')
print('selftests groups', t['groups'], 'tests', t['tests'])
k = load('kirimasim/summary.json')
print('kirimasim success', k['success'], k['passed'], '/', k['planned'], k['native'], k['returncodes'])
PY
```

macOSの結果は次のとおりです。件数はOSに依存しないはずなので、違っていたら原因を調べます。

| 検査 | macOSの結果 |
| --- | --- |
| 文書検査 | 461判定がすべて合格（この資料を含む） |
| セルフテスト | 130グループ、1,188件、skipなし（`summary.json`の予定は132判定） |
| 全例smoke | 108／108 |
| 全例nightly | 108／108 |
| kirimasim | 107／107。lowering 936回、シミュレーション2,367回、全起動の終了コード0が2,495回・1が808回（loweringを含む）、異常終了0回 |

`success`と`complete`がどちらもtrueであることを確かめます。終了コード0だけでは合格にしません。

合格の結果でも、次は変わります。問題ではありません。

- ツールとライブラリーのパス。ngspiceは`libngspice.so`になります。
- OSS CAD Suiteのハッシュ。Linux x64用の値が[`oss_cad.json`](../tools/oss_cad.json)に固定されています。
- コンパイラーの警告文と実行時間。

## 7. 失敗したとき

計画の件数、検査、時間上限を減らして合格させないでください。失敗を再実行の結果で置き換えないでください。再実行は別の`--out`で行い、[履歴レポート](../tools/REPORTING.md)に`--campaign`を複数渡すと、初回の失敗を残したまま判定できます。

まず、同じコミットのCIが合格しているかを確かめます。CIも失敗するならリポジトリの問題の可能性が高く、CIが合格するならWSLの環境の違いから調べます。

| 症状 | 原因の候補 |
| --- | --- |
| `unsupported OSS CAD platform: linux-arm64` | Arm版のWindows。固定版がないので、この範囲は実行できない |
| OSS CAD Suiteの`inventory`が失敗する | `/mnt/c`の下で作業している。同梱のPythonを直接起動した |
| パッチ、生成器の出力、lintのハッシュが合わない | 改行がCRLFになっている |
| `npm`やNode.jsでパスが`/mnt/c`のエラーが出る | Windows側のコマンドが使われている |
| `local-cocotb`でlibpythonが見つからない | 共有ライブラリーのないPythonからvenvを作った |
| コンパイラーが`Killed`で落ちる | メモリー不足。`--jobs`を下げるか、Windows側の`.wslconfig`で`memory`を増やす |
| 60秒の時間切れが一部の例で出る | 並列数が多すぎる可能性がある。`--jobs`を下げ、別の`--out`で再実行し、両方を記録する |
| `stale source`、`campaign source changed`、`source-freshness`の失敗 | 実行中に作業ツリーを変更した |

kirimasimだけが失敗するなら、同じ例をIcarusでも実行します。Icarusは合格し、kirimasimの`events/`に未実装や異常終了があれば、kirimasim側の差です。Linuxに固有の結果として記録し、テストベンチを直す前に原因を確かめます。

## 8. 結果を記録する

[`PROVENANCE.md`](../PROVENANCE.md)に新しい節を追加します。過去の節は書き換えません。次を書きます。

- 日付と、検証したコミット。
- WSLの版、Ubuntuの版、CPU数とメモリー、GCC・Python・Node.jsの版。
- 第6節の出力と、macOSの結果との違い。
- 失敗した試行とその原因。この手順から直した箇所。

`artifacts/`の証跡はGit管理外なので、そのマシンに残ります。

## CIの状態

`05e957f`のQualityとAffected（`42285207844`）は合格しました。Affectedは全例108／108のsmokeを実行し、比較基準は`6e87b32`でした。文書だけの`b18e36b`では、比較基準は`05e957f`で、回路は0件でした。

`0dd92f8`では、Nightly（`42310539185`）が全セルフテストと全例108／108のnightlyに合格し、Kirimasim latest（`42308647137`）が`b279f56275cd`で107／107に合格しました。今の状態は次で確認します。

```sh
gh run list --workflow nightly.yml --limit 3
gh run list --workflow kirimasim.yml --limit 3
```

## 作業の約束

Claude Codeのメモリーは別のマシンへ引き継がれないので、ここに書きます。

- 報告は日本語で行います。
- pushは「コミットしてmainにpush」と言われたときだけ行います。ブランチやpull requestは作らず、mainへ直接pushします。
- 長い作業の途中で、pushせずにローカルでコミットするのは構いません。
- pushには`gh auth login`と`gh auth setup-git`が必要です。

[レビューの未解決の項目](../PROVENANCE.md#repository-review-20261107)は、この確認の範囲に含めません。
