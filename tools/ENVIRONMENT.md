# 検証環境をまとめて準備・診断する

[`setup_environment.py`](setup_environment.py)は、専用Python環境・固定版パッケージ・公式UVMを新しいディレクトリへ準備し、最後に実行環境を診断します。[`check_environment.py`](check_environment.py)は既存環境の診断だけを行います。いずれもOSのパッケージ管理やシェルの設定は変更しません。

## 1. 必要な範囲を選ぶ

| プロファイル | Python | 準備・診断する範囲 |
| --- | --- | --- |
| `docs` | 3.10以上 | Markdown・PyYAML、Git、Node.js 22以上・npm、固定版Mermaidの構文解析 |
| `smoke` | 3.10以上 | 標準ライブラリ用venv、Icarus 14系、Verilator 5.052、C++20・C11、make |
| `full` | 3.13以上 | 上記全部、SystemRDL・cocotb・Z3、専用フォーマルvenv、公式UVM、OpenSTA 3.1.0、LLVM |

全例の準備には`full`を使います。Pythonパッケージの版とネイティブツールのソース版は[`environment.json`](environment.json)、インストール対象は[文書用](docs-requirements.txt)・[シミュレーション用](simulation-requirements.txt)・[フォーマル用](../examples/local-fifo-formal/tools-requirements.txt)に固定しています。OS・コンパイラー・すべての推移依存まで固定したコンテナではありません。

## 2. OS側の依存を用意する

文書だけならPython・Git・Node.js・npmを用意し、次節へ進めます。全例ではC/C++コンパイラー、make、LLVMとネイティブEDAツールも必要です。CIはUbuntu 24.04を基準に、次の開発用パッケージからソースビルドします。

```sh
sudo apt-get update
sudo apt-get install -y autoconf automake bison cmake flex g++ gcc gperf \
  help2man libeigen3-dev libfl-dev libtool llvm make ninja-build perl tcl-dev zlib1g-dev swig
python3 tools/build_native.py --profile full --jobs 2 --out artifacts/toolchains/native
```

[`build_native.py`](build_native.py)はIcarus・Verilator・CUDD・OpenSTAの登録済みGitコミットをチェックアウトし、`--out`配下でビルドして`install/`へインストールします。各段階のコマンド・時間上限・ログ・実際のコミットを残し、版不一致やビルド失敗を拒否します。`smoke`ならIcarusとVerilatorだけを構築します。ソース取得にはネットワークが必要です。外部ツールのソース・ライセンスはこの出力先へ保存され、リポジトリには取り込みません。

CUDDは古いAutomakeの版を参照する生成済みファイルを含むため、`autoreconf -fi`で現在のAutoconf・Automake・Libtoolに合わせて再生成します。

macOSではXcode Command Line ToolsとGit・Python・Node.jsを準備し、Icarus／Verilator／LLVMは使用する配布物の版を確認してください。Homebrewで別の版が入った場合、診断を通すために版チェックを外さず、登録コミットからの構築や専用のインストール先を使います。OpenSTAのmacOSでの構築例は[STAの手順](../examples/local-sta/README.md)にあります。Linux用の上記`apt-get`はmacOSでは実行しません。

## 3. 専用環境を作る

リポジトリのルートから、存在しない出力先を指定します。

```sh
# 文書のみ
python3 tools/setup_environment.py --profile docs --out artifacts/toolchains/docs
artifacts/toolchains/docs/python/bin/python tools/check_docs.py --out artifacts/docs-check

# 全例：事前にネイティブツールを用意した場合
python3.13 tools/setup_environment.py --profile full \
  --tool-bin artifacts/toolchains/native/install/bin --out artifacts/toolchains/full
```

`--python`でvenv作成元のPythonを選べます。`--tool-bin`は繰り返し指定でき、診断する子プロセスのPATHへ追加します。既存のOpenSTAなど、別のインストール先のbinも指定できます。macOSのLLVMは配布先の`bin`も追加します。

`full`の出力は、`python/`がシミュレーション・文書用、`formal/`がフォーマル用、`uvm/1800.2-2020.3.2/`が公式UVMです。UVMは既存の[準備ツール](../examples/local-uvm/setup_uvm.py)でアーカイブのSHA-256を確認し、診断時にも[`uvm-source-sha256.json`](uvm-source-sha256.json)で全ソース・LICENSE・NOTICEを照合します。変更・欠落・追加されたソースは失敗です。

準備にはpip・npm・公式UVMの取得先への通信が必要です。`npm ci --ignore-scripts`はロックファイルに従い、文書用の`tools/docs/node_modules/`へ配置します。同じ作業ツリーで準備と文書検査を同時実行しないでください。

## 4. 診断結果を読む

```sh
artifacts/toolchains/full/python/bin/python tools/check_environment.py --profile full \
  --formal-python artifacts/toolchains/full/formal/bin/python \
  --uvm-home artifacts/toolchains/full/uvm/1800.2-2020.3.2 \
  --tool-bin artifacts/toolchains/native/install/bin --out artifacts/environment-recheck
```

診断では、名前がPATH上にあるだけでなく、版の実行、Pythonパッケージの読み込みと版、C++20・C11の構文コンパイル、Mermaid図の構文解析を確認します。Icarus 14系・Verilator 5.052等の対応範囲は診断コードに明示しています。CIでのソース版はさらにコミットで固定します。Verilatorの配布元ごとに異なるビルド識別文字列もログへ保持します。

`manifest.json`は予定チェックと入力ハッシュ、`summary.json`は完了と合否、`junit.xml`は結果表示用です。`tools.json`と各ログで実際の版・起動先・不足時の案内を確認できます。`--timeout`は子コマンドごとの有限の上限です。時間切れ・起動失敗・依存の準備失敗は合格になりません。途中失敗後も元の出力は残し、新しい`--out`で再試行します。準備後の`next-command.txt`にも、別の診断出力先を使うコマンドを保存します。

環境診断の合格は回路検証の合格ではありません。準備後に[全例の実行](REGRESSION.md)と[セルフテスト](QUALITY.md#セルフテスト)を実行し、予定範囲と結果を確認してください。[CIの運用](CI.md)も同じ入口を使います。
