// Local revision (2026-10-26): require re-review of stale acceptance snapshots.
export const meta = {
  name: 'ieee-gap-tests-v2',
  description: 'Match existing tests or write new standard-derived tests for open IEEE 1800-2023 requirements, then independently verify tests and mappings',
  phases: [
    { title: 'Write', detail: 'one writer per partition (matching first in combined mode)' },
    { title: 'Verify', detail: 'independent verifier for new tests and all mappings' },
  ],
}
// Arguments (Workflow args): repo = repository root, work = work directory
// with assign/, proposals/ and notes/, pdf = the IEEE 1800-2023 PDF,
// iverilogBin = bin directory of Icarus Verilog 13.0 (optional).
// See tools/matching_kit/README.md.
const REPO = args.repo
const WORK = args.work
const PDF = args.pdf
const KIT = `${REPO}/tools/matching_kit/propose.py`
const RUNSIM = `${REPO}/tools/matching_kit/runsim.py${args.iverilogBin ? ` --iverilog-bin ${args.iverilogBin}` : ''}`
const RULES = `
作業場所: ${REPO}（コマンドはリポジトリルートで、相対パスまたは絶対パスで実行）。
変更してよいのは、tests/ 以下にあなたが新しく作るテストのファイル（.sv / .expected / .c / :files: の補助ファイル）だけ。既存のテスト（他の担当者が作った新規テストも含む）、tools/、coverage/、docs/、README.md、generators/ は変更しない。git 操作もしない。規格の本文・例・図をテストやコメントへ写さない（自分の言葉で説明し、節番号を引用する）。
まず README.md の「Test format」「Metadata」「How a test is judged」「Tests with C code」「Where the expected outputs come from」（288〜442行付近）と「Contributing」（692〜765行付近）を読み、その規則に従う。同じ章の既存テストを数本読んで書き方を合わせる。
道具:
  python3 ${KIT} req <ID> [...]            要求の behavior / acceptance / 出典ブロック / 候補テスト（既存の保留も表示）
  python3 ${KIT} test <tests/chN/test_x.sv> テストのヘッダ・入力ファイル・既存リンク・既存の保留
  python3 tools/requirement_source.py --show <節番号> [...]   規格の該当節本文
  規格PDF（図表の確認用）: ${PDF}
  python3 tools/new_test.py chNN test_name --lrm "節 ..." [--illegal]   テストの雛形を作る（既存ファイルは上書きしない）
  python3 ${RUNSIM} tests/chNN/test_x.sv [...]   Icarus Verilog 13.0 と Verilator 5.052（seed 1 / 73）で実行し、期待出力と一致するかを表示
  python3 tools/lint_metadata.py tests/chNN/test_x.sv   メタデータと書式の検査（new problem 0 にする）
`

const CRITERIA = `
対応の基準（既存テストでも新規テストでも同じ）:
- 要求の behavior と acceptance の全条件を、テストの刺激が実際に起こし、期待出力がその結果を具体的な値・時刻・型・対象で比較している。
- 「この動作を誤実装したら期待出力が変わるか」に具体的に答えられる。真になる入力だけ、個数だけ、別の型へ代入して元の型が見えない、規格が順序を決めない評価に依存する、といった観測は要求全体の証拠にしない。
- 独立した複数条件の一部しか観測しないなら登録しない（複数テストで全条件を分担できるなら group）。
- 違法系（kind=error）の要求は、:should_fail_because: 付きの負テストが意図した規格違反の診断を照合している場合だけ。正常系の要求に負テストは使えない（道具が拒否する）。
- 既存の保留（HELD）・取り下げ（WITHDRAWN）・BLOCKED は道具が拒否する。その理由を回避しようとしない。

これまでの独立検証でテストが欠陥とされた主な理由（書く側は避け、検証する側は必ず確かめる）:
- ANSI 形式のポート宣言で種類（net/var）を省いた入力ポートは、既定のネット型のネットになる（23.2.2.3）。ネットに使えるのは4状態の整数型とその配列・構造体だけなので（6.7.1）、input int / input bit / 2状態型の struct / 仮想インターフェースの入力は違法。input var int のように var を付ける。inout は var にできない。
- 違法系の :expected_stderr_regex: が、違反のある行（// illegal を付けた行）ではなく、前後の合法な行を指している。正しい実装がその行で報告することを確かめる。
- 違法系に、意図した違反とは別の違反が同じ箇所に重なる（例: automatic タスクの項目への階層参照は 13.3.1 で別に違法、mailbox のメソッドの引数型が mailbox の型と等価でない）。違反を1つにし、それを除いた設計にエラーがないことを確かめる。
- 違反の行に付けた説明のコメントが、それ自体で違反になる（\`line と同じ行のコメントは 22.12 で禁止）。指令の行にはコメントを置かない。
- 正常系に、規格上合法といえない構文がある（例: 基底の protected virtual メソッドを修飾なしで override する、int になる ?: の結果をキャストなしで enum 型へ返す）。
- 強度（%v、駆動強度、pull、tri-state）を出力するのに :fourstate: no になっている。強度の構文を使うテストは :fourstate: yes。
- 規格が決めない値を出力している（未サイズの値の $bits、同時刻の事象の順序、規定のない VPI の反復順や要素名、32ビットのプロパティへの vpi_get64 など）。
- :lrm: に、検証しない背景の節を書いている。:lrm: には検証する節だけを書く（引用した節には2本以上のテストが必要なので、背景の節を1本だけで引用すると深さの検査に掛かる）。
`

const ANNEX_A = `
附属書 A（構文）の要求について:
- 各行は BNF の生成規則・選択肢・脚注の制約です。その構文を使う正常系テストを書き、構文が受理されることに加えて、その構文で書いた要素の意味（値・動作・時刻）を出力で確かめる。受理されるだけで何も観測しないテストにしない。
- 「X は Y を許す（permits Y）」の行は、Y を使い Y の効果を出力で確認すれば満たせる。要素の並び（属性、キーワード、省略可能な要素、繰り返し）を述べる行は、省略可能な要素と繰り返しを実際に使った形を含め、述べられた全要素を使う。1本のテストで同じ生成規則の複数の選択肢をまとめてよい。
- :lrm: の先頭はその構文の意味を定める本文の章の節にし（テストはその章のディレクトリに置く）、A の節を続けて引用する。対応付ける要求の節（A.x.y）は必ず :lrm: に含める。
- 脚注（A.10）の制約は、kind=error の行だけ負テストにする。kind=normal の脚注は、制約を満たす正常な使い方を観測できる場合だけ扱う。
`

function writerPrompt(p) {
  const scopeCmd = `python3 ${KIT} scope ${p.assign} ${p.scopeOuts.map(o => `--out ${o}`).join(' ')}`
  const modeText = p.mode === 'combined'
    ? `進め方の最初に、各要求について候補テスト（req で表示）を確認し、既存テストが要求全体を検証していればそのテストを add する（新しいテストは書かない）。候補が多ければ grep で絞る。既存テストで検証できない要求について新しいテストを書く。`
    : `担当範囲の要求のうち、照合で対応が見つからなかったもの（scope で状態が open / open+hold のもの）について新しいテストを書く。既存テストで要求全体を検証できるものに気づいたら、そちらを add してよい。`
  return `あなたは IEEE 1800-2023 の要求に対するテストの作成担当です（担当 ${p.label}）。
目的: 担当範囲の未対応要求を、規格から期待値を導いたテストで検証し、要求との対応を照合案として登録する。後で独立した検証者が、テストの合法性・期待値・決定性と、対応の妥当性を反証しようとする。根拠の弱いテストや対応は却下され、テストも削除されるので、件数より正確さを優先する。
${RULES}
${CRITERIA}
${p.mode === 'annexA' ? ANNEX_A : ''}
あなた専用の出力:
  照合案ファイル: ${p.propOut}
  作ったテストの一覧: ${WORK}/notes/${p.label}-tests.txt（1行1テスト、tests/... の .sv パス）
  シミュレータと規格の差異メモ: ${WORK}/notes/${p.label}-simdiff.md（テスト・シミュレータ・違い・根拠節。docs/ は編集しない）
  ${scopeCmd}   担当要求の一覧と状態（MAPPED は対応済み、+check / +group は照合案あり、open / open+hold が未対応）
  python3 ${KIT} add   --out ${p.propOut} <<'JSON' ... JSON
  python3 ${KIT} group --out ${p.propOut} <<'JSON' ... JSON

${modeText}
${args.resume ? `これは中断した作業の再開です。最初に、テストの一覧ファイル、照合案ファイル（scope の状態）を確認する。一覧にあるが照合案のないテストは、lint と runsim で確認し、規格に照らして正しければ照合案を追加する。書きかけのテスト（TODO が残る、期待出力が空・ない、lint 違反）は完成させるか、あなたが作ったものなら削除して一覧から外す。そのうえで未対応の要求から続ける。` : ''}

テストの作り方:
1. 対象要求を節ごとにまとめ、節の本文（表・例外・エラー条件を含む）を読む。interpretation issue のある要求、観測可能な結果のない要求（ツールの裁量だけを述べるもの等）は対象外。
2. 1本のテストで、密接に関連する1〜数個の要求を完全に検証する。要求の全条件を刺激し、誤実装なら出力が変わるよう対照となるケースも入れる（真になる入力と偽になる入力、境界の両側、x/z を扱う要求では x と z の両方など）。出力は規格が決める値だけにし、実際の値を表示する。順序が規格で決まらないもの（同じ式の中での関数呼び出しの評価順、同時刻のプロセスの実行順など）に依存しない。
3. 期待出力は規格の該当節から導いて先に書く。その後 runsim で実行する。シミュレータの出力を期待値へ写さない。一致しない場合はまず自分の期待値と規格を再確認し、それでもシミュレータが規格と違うなら差異メモへ記録し、テストのコメントにも書く。
4. :oracle: は、Icarus 13.0 が一致すれば iverilog@13.0、Verilator の seed 1 と 73 の両方が一致すれば verilator@5.052 を spec の後に付ける。どちらも一致しなければ spec だけにし、テストのコメントに規格が何を要求するかを書く。:fourstate: は x/z を使うか出力するなら yes。時刻を表示するなら timescale を置く。コメント行を「Verilator」という語で始めない（BADVLTPRAGMA になる）。
5. 違法系（--illegal）は kind=error の要求だけに使う。エラーは1つだけにし、:expected_stderr_regex: でファイルと行を示す。未対応構文によるエラーと規格違反の検出を混同しない。
6. VPI / DPI のテストは README の「Tests with C code」に従う（C と C++ の両方でコンパイルできる、extern "C"、出力は vpi_printf か printf+fflush）。Verilator は VPI で登録したシステムタスクを呼べないので、VPI の出力は cbStartOfSimulation などのコールバックや vlog_startup_routines から行う既存テストの書き方を参考にする。
7. 実行時間が長いテスト（数秒を超える）や巨大なメモリを使うテストは避ける。
8. lint を通し、テストの一覧ファイルへ追記する。テストを確定させてから（以後変更しない）、対応する要求ごとに add する。evidence は .sv の刺激の行と .expected の結果の行（C があれば判定箇所も）。observation と rationale は日本語で具体的に（どの誤実装で、どの出力行がどう変わるか）。
9. 1本書き終えるごとに次へ進む。できるだけ多くの対象要求を、品質を落とさずにカバーする（目安として20〜40本）。担当範囲の対象を一通り検討し終えるか、これ以上良いテストを書けなくなったら終了する。

最後に、作ったテスト数、登録した照合案数（既存テスト/新規テスト別）、対象外とした要求の主な理由を返す。`
}

function verifierPrompt(p) {
  return `あなたはテストと対応の独立検証者です（担当 ${p.label}）。別の担当者が作った新規テストが規格に照らして正しいか、そして照合案（既存テストへの対応と新規テストへの対応）が要求全体を検証しているかを反証しようとしてください。
${RULES}
${CRITERIA}
${p.mode === 'annexA' ? ANNEX_A : ''}
対象:
  新規テストの一覧: ${WORK}/notes/${p.label}-tests.txt
  照合案ファイル: ${p.propOut}（1行1件の JSON。python3 ${KIT} show --out ${p.propOut} で一覧）
記録:
  テストの判定: python3 ${KIT} testverdict --out ${WORK}/notes/${p.label}-testverdicts.jsonl --test <tests/...sv> (--ok|--defective) --reason '<理由>' --verifier '${p.label}-verifier'
  照合案の判定: python3 ${KIT} verdict --out ${p.propOut} --key '<key>' (--accept|--reject) --reason '<理由>' --verifier '${p.label}-verifier'

各新規テストについて（照合案より先に）:
1. 引用節の本文を読み、期待出力の全行を規格から自分で導いて照合する。テストのコメントや作者の説明を鵜呑みにしない。
2. 正常系として合法か（違法な構文・未定義の動作・規格が決めない順序や値への依存がないか）、:fourstate: / :oracle: / timescale などのメタデータが正しいか、lint が通るか、規格の本文・例をそのまま写していないか、実行時間が過大でないかを確認する。
3. runsim で実行し、:oracle: に書かれたシミュレータが実際に一致するかを確かめる。一致しないシミュレータについて、規格と違うのがシミュレータ側だと確認できるか。
4. 問題があれば defective、なければ ok を記録する。期待値が規格から導けない、または誤っているテストは必ず defective。

各照合案（type=check / group）について:
- 新規テストが defective なら reject。
- 刺激が要求の全条件を起こし、期待出力が誤実装と区別できるかを確かめる。独立した複数条件の一部しか見ていない、誤実装でも同じ出力になる、anchor が無関係、違法系なのに意図した違反を照合していない、のどれかなら reject。不確かなら reject。
type=hold は、explanation が具体的で正しいと確認できれば accept、曖昧・誤りなら reject。

すべてのテストと照合案に判定を付け、最後に show で [no verdict] と [stale: ...] がないことを確認する。accept は照合案・テスト入力・要求の承認時ハッシュを記録する。古い承認や変更済みの入力は、現行の内容を独立に再レビューしてから再承認する。最後に ok / defective のテスト数、accept / reject 件数、主な理由を返す。`
}

const WRITE_SCHEMA = { type: 'object', properties: { tests_written: { type: 'integer' }, proposals: { type: 'integer' }, notes: { type: 'string' } }, required: ['tests_written', 'proposals', 'notes'] }
const VERIFY_SCHEMA = { type: 'object', properties: { tests_ok: { type: 'integer' }, tests_defective: { type: 'integer' }, accepted: { type: 'integer' }, rejected: { type: 'integer' }, findings: { type: 'string' } }, required: ['tests_ok', 'tests_defective', 'accepted', 'rejected', 'findings'] }

const parts = args.parts.map(x => {
  const dir = `${WORK}/proposals/${x.wave}`
  const own = x.mode === 'gap' ? `${dir}/${x.label}-gap.jsonl` : `${dir}/${x.label}.jsonl`
  const scopeOuts = x.mode === 'gap' ? [`${dir}/${x.label}.jsonl`, own] : [own]
  return { label: x.label, mode: x.mode, assign: `${WORK}/assign/${x.label}.json`, propOut: own, scopeOuts }
})
log(`${parts.length} partitions: ${parts.map(p => `${p.label}(${p.mode})`).join(', ')}`)
if (args.verifyOnly) {
  return await parallel(parts.map(p => () =>
    agent(verifierPrompt(p), { label: `verify:${p.label}`, phase: 'Verify', schema: VERIFY_SCHEMA })
      .then(v => ({ label: p.label, mode: p.mode, verify: v }))))
}
return await pipeline(
  parts,
  p => agent(writerPrompt(p), { label: `write:${p.label}`, phase: 'Write', schema: WRITE_SCHEMA }),
  (w, p) => agent(verifierPrompt(p), { label: `verify:${p.label}`, phase: 'Verify', schema: VERIFY_SCHEMA })
    .then(v => ({ label: p.label, mode: p.mode, write: w, verify: v })),
)
