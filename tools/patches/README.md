# ngspice 47の初期化互換パッチ

[ngspice-47-init.patch](ngspice-47-init.patch)は、[固定版ngspice](../ngspice.json)の`src/sharedspice.c`へ適用する修正です。元コードと修正部分にはModified BSD（BSD-3-Clause）を適用します。著作権・利用条件は[ngspice-47-LICENSE](ngspice-47-LICENSE)に保持しています。

公開ヘッダーでは`ngSpice_nospinit()`・`ngSpice_nospiceinit()`を`ngSpice_Init()`より前に呼ぶよう定めています。revision `a80f6e3e95d51534905b1f23410a951802666656`では、この呼出しが未初期化の`ft_sim`を参照して異常終了することを再現しました。また、Unixのユーザー設定読込み分岐では、抑止フラグが確認されていませんでした。

修正では初期化前の指定を保留し、`SIMinit`後に設定します。Unixでもユーザー設定を抑止するフラグを確認します。通常の初期化は維持し、教材では呼出し元の設定ファイルに依存しない実行を選びます。

[`setup_ngspice.py`](../setup_ngspice.py)は、公式Gitコミットと差分のSHA-256、適用前・適用後のソースSHA-256を照合して構築します。診断ではAPIを指定順に呼び、作業ディレクトリの検出用`.spiceinit`が実行されないことと、実際のRC過渡解析が解析解に一致することを確認します。上流への修正送付は行っていません。

参照：[ngspice共有ライブラリーの説明](https://ngspice.sourceforge.io/shared.html)、[修正対象の原版](https://sourceforge.net/p/ngspice/ngspice/ci/a80f6e3e95d51534905b1f23410a951802666656/tree/src/sharedspice.c)。
