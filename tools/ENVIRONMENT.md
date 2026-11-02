# 検証環境をまとめて準備・診断する

[`setup_environment.py`](setup_environment.py)は、専用Python環境・固定版パッケージ・公式UVM・OSS CAD Suiteを新しいディレクトリへ準備し、最後に実行環境を診断します。[`check_environment.py`](check_environment.py)は既存環境の診断だけを行います。いずれもOSのパッケージ管理やシェルの設定は変更しません。

## 1. 必要な範囲を選ぶ

| プロファイル | Python | 準備・診断する範囲 |
| --- | --- | --- |
| `docs` | 3.10以上 | Markdown・PyYAML、Git、Node.js 22以上・npm、固定版Mermaidの構文解析 |
| `smoke` | 3.10以上 | 標準ライブラリ用venv、Icarus 14系、Verilator 5.052、C++20・C11、make |
| `full` | 3.13以上 | 上記全部、SystemRDL・cocotb・Z3、専用フォーマルvenv、公式UVM、固定版OSS CAD Suite、OpenSTA 3.1.0、LLVM、SystemC 2.3.4、ngspice 47共有ライブラリー |

全例の準備には`full`を使います。Pythonパッケージの版とネイティブツールのソース版は[`environment.json`](environment.json)、インストール対象は[文書用](docs-requirements.txt)・[シミュレーション用](simulation-requirements.txt)・[フォーマル用](../examples/local-fifo-formal/tools-requirements.txt)に固定しています。OS・コンパイラー・すべての推移依存まで固定したコンテナではありません。

## 2. OS側の依存を用意する

文書だけならPython・Git・Node.js・npmを用意し、次節へ進めます。全例ではC/C++コンパイラー、make、LLVMとネイティブEDAツールも必要です。CIはUbuntu 24.04を基準に、次の開発用パッケージからソースビルドします。

```sh
sudo apt-get update
sudo apt-get install -y autoconf automake bison cmake flex g++ gcc gperf \
  help2man libeigen3-dev libfl-dev libtool llvm make ninja-build perl tcl-dev zlib1g-dev swig
python3 tools/build_native.py --profile full --jobs 2 --out artifacts/toolchains/native
```

[`build_native.py`](build_native.py)はIcarus・Verilator・CUDD・OpenSTA・SystemCの登録済みGitコミットをチェックアウトし、`--out`配下でビルドして`install/`へインストールします。各段階のコマンド・時間上限・ログ・実際のコミットを残し、版不一致やビルド失敗を拒否します。`smoke`ならIcarusとVerilatorだけを構築します。ソース取得にはネットワークが必要です。外部ツールのソース・ライセンスはこの出力先へ保存され、リポジトリには取り込みません。

CUDDは古いAutomakeの版を参照する生成済みファイルを含むため、`autoreconf -fi`で現在のAutoconf・Automake・Libtoolに合わせて再生成します。

macOSではXcode Command Line ToolsとGit・Python・Node.jsを準備し、Icarus／Verilator／LLVMは使用する配布物の版を確認してください。Homebrewで別の版が入った場合、診断を通すために版チェックを外さず、登録コミットからの構築や専用のインストール先を使います。OpenSTAのmacOSでの構築例は[STAの手順](../examples/local-sta/README.md)にあります。Linux用の上記`apt-get`はmacOSでは実行しません。

## 3. 専用環境を作る

リポジトリのルートから、存在しない出力先を指定します。

```sh
# 文書のみ
python3 tools/setup_environment.py --profile docs --out artifacts/toolchains/docs
artifacts/toolchains/docs/python/bin/python tools/check_docs.py --out artifacts/docs-check

# SPICE協調用の共有ライブラリーを別途準備する
python3 tools/setup_ngspice.py --out artifacts/toolchains/ngspice

# 全例：事前にネイティブツールを用意した場合
python3.13 tools/setup_environment.py --profile full \
  --tool-bin artifacts/toolchains/native/install/bin \
  --ngspice-home artifacts/toolchains/ngspice/install --out artifacts/toolchains/full
```

`--python`でvenv作成元のPythonを選べます。`--tool-bin`は繰り返し指定でき、診断する子プロセスのPATHへ追加します。既存のOpenSTAなど、別のインストール先のbinも指定できます。macOSのLLVMは配布先の`bin`も追加します。

`--ngspice-home`で導入済みの固定版を再利用します。省略時は新しい出力先の`ngspice/install/`へ構築し、診断のPATHへ追加します。全例実行の際は、その`bin`も`--tool-bin`へ渡してください。

`full`の出力は、`python/`がシミュレーション・文書用、`formal/`がフォーマル用、`uvm/1800.2-2020.3.2/`が公式UVMです。UVMは既存の[準備ツール](../examples/local-uvm/setup_uvm.py)でアーカイブのSHA-256を確認し、診断時にも[`uvm-source-sha256.json`](uvm-source-sha256.json)で全ソース・LICENSE・NOTICEを照合します。変更・欠落・追加されたソースは失敗です。

準備にはpip・npm・公式UVM・OSS CAD Suiteの取得先への通信が必要です。`npm ci --ignore-scripts`はロックファイルに従い、文書用の`tools/docs/node_modules/`へ配置します。同じ作業ツリーで準備と文書検査を同時実行しないでください。

## 4. 診断結果を読む

```sh
artifacts/toolchains/full/python/bin/python tools/check_environment.py --profile full \
  --formal-python artifacts/toolchains/full/formal/bin/python \
  --uvm-home artifacts/toolchains/full/uvm/1800.2-2020.3.2 \
  --oss-home artifacts/toolchains/full/oss/oss-cad-suite \
  --tool-bin artifacts/toolchains/native/install/bin \
  --tool-bin artifacts/toolchains/ngspice/install/bin --out artifacts/environment-recheck
```

診断では、名前がPATH上にあるだけでなく、版の実行、Pythonパッケージの読み込みと版、C++20・C11の構文コンパイル、Mermaid図の構文解析を確認します。Icarus 14系・Verilator 5.052等の対応範囲は診断コードに明示しています。CIでのソース版はさらにコミットで固定します。Verilatorの配布元ごとに異なるビルド識別文字列もログへ保持します。

`manifest.json`は予定チェックと入力ハッシュ、`summary.json`は完了と合否、`junit.xml`は結果表示用です。`tools.json`と各ログで実際の版・起動先・不足時の案内を確認できます。`--timeout`は子コマンドごとの有限の上限です。時間切れ・起動失敗・依存の準備失敗は合格になりません。途中失敗後も元の出力は残し、新しい`--out`で再試行します。準備後の`next-command.txt`にも、別の診断出力先を使うコマンドを保存します。

環境診断の合格は回路検証の合格ではありません。準備後に[全例の実行](REGRESSION.md)と[セルフテスト](QUALITY.md#セルフテスト)を実行し、予定範囲と結果を確認してください。[CIの運用](CI.md)も同じ入口を使います。

## OSS CAD Suiteの固定版

[自動ミューテーション](../examples/local-auto-mutation/README.md)と[期限なしの進行証明](../examples/local-liveness/README.md)は、ネイティブYosys・SBY・MCY・ABCを使います。[YosysHQ公式配布](https://github.com/YosysHQ/oss-cad-suite-build)の2026-10-31版を[`oss_cad.json`](oss_cad.json)へ固定し、Linux x64とmacOS arm64を対象にします。他のOS・CPUを別のバイナリーへ読み替えません。

```sh
# 単独で準備する。公式アーカイブを取得し、内容も照合する
python3 tools/setup_oss_cad.py --out artifacts/toolchains/oss

# 導入済みの固定版を再利用してfull環境を作る
python3.13 tools/setup_environment.py --profile full \
  --oss-home artifacts/toolchains/oss/oss-cad-suite \
  --tool-bin artifacts/toolchains/native/install/bin \
  --ngspice-home artifacts/toolchains/ngspice/install --out artifacts/toolchains/full

# 既存インストールの内容だけを再確認する
python3 tools/setup_oss_cad.py --check artifacts/toolchains/oss/oss-cad-suite
```

`full`で`--oss-home`を省くと、新しい出力先の`oss/oss-cad-suite/`へ導入します。指定した場合はその配置を変更せず、固定版の内容を確認します。`--archive`で手元の配布アーカイブを指定しても、SHA-256の照合は必須です。

アーカイブのSHA-256に加え、展開後の全ファイルのハッシュ・シンボリックリンク先・実行ビットから作るハッシュを照合します。追加・欠落・変更も失敗です。ツール起動時は`PYTHONDONTWRITEBYTECODE=1`を設定し、同梱Pythonがインストール先のキャッシュを書き換えないようにします。変更を見逃すための除外設定にはしません。

例と全体ランナーには`--oss-home`を渡します。このbinを通常のPATHの先頭へ追加すると、既存例に必要なIcarus・Verilatorの版を置き換えるため避けてください。ツール本体と各ライセンスは出力先だけに保存し、リポジトリへ再配布しません。macOS arm64版には`live`用のsuproveがないため、本例は[正確な有限状態変換とPDR](../examples/local-liveness/README.md#証明方式)を使います。

## SystemCとSoCLibの例

[SoCLibを使うVCI例](../examples/local-vci-soclib/README.md)は、Accellera公式の[SystemC 2.3.4](https://github.com/accellera-official/systemc/tree/5fc1469339775b54b1fcc2020ac744a58be5b50e)を使います。`build_native.py --profile full`は固定コミットからC++17・POSIXスレッド・静的ライブラリーとして構築し、`install/include/`、`install/lib/libsystemc.a`、`install/bin/lsi-systemc-config`へ配置します。`--tool-bin .../install/bin`を診断・全例実行へ渡してください。`smoke`環境の構築には含めません。

SoCLibコード中のGNU拡張に合わせ、例は`-std=gnu++17`でコンパイルします。SystemC側のC++規格も17でそろえています。`lsi-systemc-config --prefix`は配置先、`--version`は構築対象の版を返します。full診断ではこの表示に加え、実ライブラリーをリンクしたSystemCプログラムの起動と版も確認します。

SoCLibのCABA部品は必要なソースをリポジトリへ収録しており、旧Python版のSoCLibツールやCPU用クロスコンパイラーは使いません。収録部品のLGPLと、外部ビルドするSystemCのApache-2.0を区別します。例の実行では、使用したSystemCヘッダー・ライブラリー・設定コマンドの全対象ハッシュを保存し、変更・欠落・追加を再照合します。

## ngspiceとSPICE協調例

[SPICEとRTLの例](../examples/local-spice-cosim/README.md)は、[公式Git](https://git.code.sf.net/p/ngspice/ngspice)のngspice 47を共有ライブラリーとして構築します。版とフラグは[ngspice.json](ngspice.json)、初期化互換修正は[パッチの説明](patches/README.md)に固定しています。既存のIcarus・Verilator・SystemCのビルドとは別の出力・キャッシュを使います。

Linuxでは上記のAutoconf・Automake・Libtool・Bison・Flex・Cコンパイラー・makeを使います。macOSではCommand Line ToolsとHomebrew版を準備し、古いOS標準Bisonより先にPATHへ置きます。

```sh
brew install autoconf automake libtool bison flex
export PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:$PATH"

python3 tools/setup_ngspice.py --jobs 2 --timeout 1800 --out artifacts/toolchains/ngspice
python3 tools/setup_ngspice.py --check artifacts/toolchains/ngspice/install \
  --out artifacts/ngspice-recheck
```

上の`brew`行はmacOS用です。LinuxではOS依存の準備を済ませて`setup_ngspice.py`を実行します。`--tool-bin`も繰り返し指定でき、指定したBison・Flex等をビルド用のPATHへ追加できます。ソース取得にはネットワークが必要です。

ソースコミット、差分、適用前後の内容を照合し、GUI・readline・CIDER・OpenMPを使わない共有ライブラリーを構築します。XSPICEは有効な構成ですが、この教材の回路はR・Cと独立電圧源です。実行時にPDKやユーザーの`.spiceinit`を読み込む必要はありません。

`install/bin/lsi-ngspice-config --prefix`で配置先、`--version`で構築対象を確認できます。診断では表示だけでなく、実際のAPI初期化、設定ファイル抑止、RC過渡解析と解析解の一致を確認します。`install/share/lsi-ngspice/build.json`が版・パッチ・ファイルハッシュの記録です。欠落・変更・対象ライブラリーの追加は検査失敗になります。

full環境へ組み込む際は`setup_environment.py --profile full --ngspice-home .../install`を指定できます。`check_environment.py`と`run_regression.py`へは`--tool-bin .../install/bin`を追加します。例単独なら`--ngspice-config .../install/bin/lsi-ngspice-config`でも指定できます。

ngspice本体と各ライセンスは外部の出力先へ保持し、バイナリーをGit管理には含めません。元コードを含む互換差分のModified BSD表示は[ngspice-47-LICENSE](patches/ngspice-47-LICENSE)へ保持しています。
