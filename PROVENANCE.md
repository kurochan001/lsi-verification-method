# 由来

このリポジトリの資料とツールの基礎は、[kirimasim-tests](https://github.com/kurochan001/kirimasim-tests)から複製したものです。最初の複製はコミット`c88b0c3`（2026-10-24）からで、その後に元で更新された資料は、表に示すコミットから複製し直しています。
複製時には、Markdownの相対リンクを書き換えました。コピー先にある資料へのリンクは、新しい場所への相対リンクにしました。コピー先に無い資料へのリンクは、元のリポジトリの同じコミットへの固定リンクにしました。
`README.md`、`tools/README.md`、`PROVENANCE.md`、`.gitignore`、`docs/templates/`は、このリポジトリで新しく書いたものです。一般化した手順書には、以下の追記・改訂があります。

## このリポジトリでの追記・改訂

- `docs/method/spec-to-verification-method.md`は、下表のファイルを派生元として維持します。`3142ad7`で、製品開発の設計・検証・製造上の確認項目を14節に追加しました。
- 2026-10-25の全体レビューで、機能カバレッジと正しさの判定、構成ごとの適用と集計、証跡と形式検証の条件、仕様変更の影響確認、開発段階別のサインオフと例外承認を明確にしました。技術的な役割を確認した一次資料は、手順書の付録Cに示しています。これらは半導体仕様への適用実績ではなく、今後検証する運用案です。
- `docs/templates/signoff-record.md`は、改訂した手順に沿って新設した雛形です。`tools/README.md`には、複製元での復元先・依存ファイル・検証方法を追記しています。
- `docs/method/uvm-verification.md`は、このリポジトリで新しく書いたUVMへの適用案です。Accelleraの公式資料・参照実装を参照し、要求IDとの対応、RAL、テスト終了と回帰の判定を整理しました。一般化した手順書の9.7節と、サインオフ記録から参照します。UARTの記録例は説明用であり、実行済みの証跡ではありません。
- `docs/method/feature-interaction-verification.md`は、このリポジトリで新しく書いた機能間クロス検証の運用案です。依存関係からの目標選定、同時・順序・中断の観測、高次の組み合わせ、到達と合格の計測を追記しました。UVMの実装説明とサインオフ記録も対応させています。NISTとAccelleraの一次資料を参考にしましたが、相互作用表と割り込みIPの12目標は本リポジトリの計画例であり、適用済みの実績ではありません。
- `docs/method/constrained-random-verification.md`は、このリポジトリで新しく書いたランダム検証の運用案です。制約と探索方針、生成失敗、seedと再現性、回帰、未達の調整、失敗の縮小と完了条件を整理しました。AccelleraとVerilatorの一次資料を参照し、UVM・クロス検証・サインオフ記録も対応させています。割り込みの9実行は未実施の計画例です。
- `docs/method/sva-verification.md`は、このリポジトリで新しく書いたSVAの運用案です。assert・assume・cover、サンプリング、リセット・空成立、シミュレーション・形式検証の記録と完了条件を整理しました。DVConの著者論文とYosysHQ・Verilatorの一次資料を参照しています。割り込みのcheckerは本リポジトリで作成した説明用コードで、規格の例の転載や製品IPへの適用実績ではありません。
- `docs/method/functional-coverage.md`は、このリポジトリで新しく書いたcovergroupの運用案です。機能一覧からのbin・crossの設計、サンプリング、除外と閾値、インスタンス・DBの集計、判定との対応を整理しました。Accellera・OpenTitan・Verilatorの一次資料を参照しています。基本動作の16目標を扱うcollectorは本リポジトリで作成した説明用コードです。
- `docs/method/formal-verification.md`は、このリポジトリで新しく書いたフォーマル検証の運用案です。仮定・初期状態、抽象化と証明の分割、安全性・活性、有界検査と非有界の証明、反例・到達性、完了判定を整理しました。YosysHQ・YoWASPの一次資料を参照しています。割り込みの小さなモデル、証明設定と故障注入は本リポジトリで作成し、説明用モデルで動作確認したもので、製品IPへの適用実績ではありません。
- `docs/method/verification-gap-review.md`と`docs/templates/verification-scope.md`は、このリポジトリで新しく書いた検証領域の点検手順と適用範囲の雛形です。既存資料で概要にとどまっていた領域を、lint、リセット・X伝搬、CDC/RDC、転送・異常・復帰、性能、低電力、セキュリティ、コードカバレッジ、等価性・統合などの試験・解析と完了条件へ展開しました。OpenTitan・Verilator・Accelleraの一次資料を参照しています。割り込みの追加試験案は未実施の計画で、製品への適用実績ではありません。
- 同資料のCDC検証に、同期化レイテンシをランダムに変えるDynamic CDC／メタスタビリティ影響注入を追記しました。Siemensの著者解説とsemifyの公開モデルを参照し、クロックジッター・実行ごとのFF段数変更との区別、−1／0／＋1のモデル条件、再収束と観測・判定を整理しています。外部モデルの導入・転載・動作確認を行ったものではありません。
- `docs/method/mutation-verification.md`は、このリポジトリで新しく書いたミューテーション検証の運用案です。YosysHQ MCYの一次資料を参照し、検証環境の検出力と安全機構への故障注入の区別、変異の選定、対照実行、未検出・等価性の分析、分類・集計・証跡を整理しました。割り込みの確認例は、既存のSVA・形式検証資料に記録した説明用モデルの結果を参照しています。MCYの導入や製品での変異キャンペーンの実施を示すものではありません。
- ケーススタディの報告とツールのコードは、上流の履歴を示す資料・参照実装として扱います。一般化した手順書の追加項目が、そのまま現行ツールで検査できるという意味ではありません。

## 最新版との照合

2026-10-25の同期時に上流を取得し、その時点の最新`main`の[`3faf239af2614fd8d65cf31c54b0f297108704dd`](https://github.com/kurochan001/kirimasim-tests/commit/3faf239af2614fd8d65cf31c54b0f297108704dd)に対して、下表の全32ファイルを照合しました。変更のあったツール4ファイルを更新しました。内容が変わっていないファイルは、従来の複製元コミットを残しています。その後の一般化文書の追記・改訂は上記に分けて記録しています。

今回のツール更新には、指摘番号が付いた保留判定の重複登録防止、テスト作成・独立検証時の注意事項の追加、計測対象シミュレータのLyraへの更新、環境変数`IEEE1800_SOURCE`による規格資料の参照先指定を含みます。
また、`simulator-differences.md`で過去のリンク書き換えが配列の説明とコード例に入り込んでいた2箇所を、上流の記述に戻しました。

## ファイルごとの複製元・派生元

| このリポジトリ | kirimasim-tests（複製元のコミット） |
| --- | --- |
| `docs/method/spec-to-verification-method.md` | [`docs/spec-to-verification-method.md`](https://github.com/kurochan001/kirimasim-tests/blob/0ccbd37/docs/spec-to-verification-method.md) |
| `docs/case-study-ieee1800/requirements-to-tests-method.md` | [`docs/requirements-to-tests-method.md`](https://github.com/kurochan001/kirimasim-tests/blob/c8afe0e/docs/requirements-to-tests-method.md) |
| `docs/case-study-ieee1800/requirement-extraction.md` | [`docs/requirement-extraction.md`](https://github.com/kurochan001/kirimasim-tests/blob/0ccbd37/docs/requirement-extraction.md) |
| `docs/case-study-ieee1800/requirement-extraction-notes.md` | [`docs/requirement-extraction-notes.md`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/requirement-extraction-notes.md) |
| `docs/case-study-ieee1800/coverage-rules.md` | [`coverage/README.md`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/coverage/README.md) |
| `docs/case-study-ieee1800/existing-test-matching-20percent-20261023.md` | [`docs/existing-test-matching-20percent-20261023.md`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/existing-test-matching-20percent-20261023.md) |
| `docs/case-study-ieee1800/existing-test-matching-review-20261022.md` | [`docs/existing-test-matching-review-20261022.md`](https://github.com/kurochan001/kirimasim-tests/blob/0ccbd37/docs/existing-test-matching-review-20261022.md) |
| `docs/case-study-ieee1800/header-vpi-tests-and-matching-20261023.md` | [`docs/header-vpi-tests-and-matching-20261023.md`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/header-vpi-tests-and-matching-20261023.md) |
| `docs/case-study-ieee1800/keyword-tests-20261024.md` | [`docs/keyword-tests-20261024.md`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/docs/keyword-tests-20261024.md) |
| `docs/case-study-ieee1800/gap-tests-20261024.md` | [`docs/gap-tests-20261024.md`](https://github.com/kurochan001/kirimasim-tests/blob/b13204c/docs/gap-tests-20261024.md) |
| `docs/case-study-ieee1800/gap-tests-2-20261024.md` | [`docs/gap-tests-2-20261024.md`](https://github.com/kurochan001/kirimasim-tests/blob/0ccbd37/docs/gap-tests-2-20261024.md) |
| `docs/case-study-ieee1800/lyra-disagreement-review-20261025.md` | [`docs/lyra-disagreement-review-20261025.md`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/docs/lyra-disagreement-review-20261025.md) |
| `docs/case-study-ieee1800/simulator-differences.md` | [`docs/simulator-differences.md`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/docs/simulator-differences.md) |
| `tools/matching_kit/README.md` | [`tools/matching_kit/README.md`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/README.md) |
| `tools/matching_kit/propose.py` | [`tools/matching_kit/propose.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/propose.py) |
| `tools/matching_kit/merge.py` | [`tools/matching_kit/merge.py`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/tools/matching_kit/merge.py) |
| `tools/matching_kit/runsim.py` | [`tools/matching_kit/runsim.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/runsim.py) |
| `tools/matching_kit/partition.py` | [`tools/matching_kit/partition.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/partition.py) |
| `tools/matching_kit/withdrawn-20261023.json` | [`tools/matching_kit/withdrawn-20261023.json`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/withdrawn-20261023.json) |
| `tools/matching_kit/workflows/match.js` | [`tools/matching_kit/workflows/match.js`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/workflows/match.js) |
| `tools/matching_kit/workflows/gap.js` | [`tools/matching_kit/workflows/gap.js`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/tools/matching_kit/workflows/gap.js) |
| `tools/matching_kit/workflows/interpretation-review.js` | [`tools/matching_kit/workflows/interpretation-review.js`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/matching_kit/workflows/interpretation-review.js) |
| `tools/matching_kit/test_matching_kit.py` | [`tools/test_matching_kit.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/test_matching_kit.py) |
| `tools/generators/common.py` | [`generators/common.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/generators/common.py) |
| `tools/generators/generate.py` | [`generators/generate.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/generators/generate.py) |
| `tools/generators/keywords.py` | [`generators/keywords.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/generators/keywords.py) |
| `tools/reference/behavior_coverage.py` | [`tools/behavior_coverage.py`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/tools/behavior_coverage.py) |
| `tools/reference/requirement_audit.py` | [`tools/requirement_audit.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/requirement_audit.py) |
| `tools/reference/requirement_matching.py` | [`tools/requirement_matching.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/requirement_matching.py) |
| `tools/reference/requirement_source.py` | [`tools/requirement_source.py`](https://github.com/kurochan001/kirimasim-tests/blob/3faf239/tools/requirement_source.py) |
| `tools/reference/suite_results.py` | [`tools/suite_results.py`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/tools/suite_results.py) |
| `LICENSE` | [`LICENSE`](https://github.com/kurochan001/kirimasim-tests/blob/c88b0c3/LICENSE) |
