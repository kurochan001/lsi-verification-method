// Local revision (2026-10-26): require re-review of stale acceptance snapshots.
export const meta = {
  name: 'ieee-match-wave',
  description: 'Propose and adversarially verify IEEE 1800-2023 requirement links to existing tests, one matcher + one verifier per partition',
  phases: [
    { title: 'Match', detail: 'one matcher per partition proposes links via the kit' },
    { title: 'Verify', detail: 'independent verifier records accept/reject for every proposal' },
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
const COMMON_RULES = `
禁止事項:
- リポジトリ内のファイルを一切変更しない（tests/, coverage/, docs/, tools/ のすべて）。git操作もしない。シミュレータを実行しない。
- 規格本文をファイルへコピーしない。
- 自分に割り当てられた出力ファイル以外へ書き込まない。
- 作業はリポジトリルート ${REPO} で行う（コマンドは cd せず絶対パスか、ルートからの相対パスで）。

道具（K=${KIT}）:
  python3 ${KIT} req <ID> [...]               要求の behavior/acceptance/出典ブロック、候補テスト、既存の保留
  python3 ${KIT} test <tests/chN/test_x.sv>  テストのヘッダ、入力ファイル、既存リンク、既存保留
  python3 tools/requirement_source.py --show <節番号> [...]   規格の該当節本文（ブロックID付き）
規格PDFの図表を確認したい場合は ${PDF} を読んでよい（コピーはしない）。
`

const CRITERIA = `
登録基準（すべて満たす場合だけ）:
- 要求の behavior と acceptance の全条件を、テストの刺激が実際に起こし、期待出力がその結果を具体的な値・時刻・型・対象で比較している。
- 「この動作を誤実装したら期待出力が変わるか」に具体的に答えられる（例: 余りの符号を第2オペランドから取る誤実装なら -7 % 2 の期待値 -1 が 1 になる）。
- 引用節・テスト名・説明文・APIが呼ばれた事実だけでは登録しない。非NULLだけの確認、常に0でも通る検査、真になる入力しかない関係演算子、別の型へ代入したため元の戻り型を区別できない確認、count/typeだけで正しい対象の同一性や値を確かめない検査、callbackと副作用の前後関係を確かめない検査は、要求全体の証拠にしない。
- 要求が独立した複数条件からなり、テストが一部しか観測しないなら登録しない。全条件を複数テストで分担できるなら group（AND集合）にする。単独で要求全体を満たすテストが複数あれば、それぞれ add してよい。
- 期待出力が規格と矛盾する、正常系テストが規格上違法な構文を含む、期待値がシミュレータの挙動に合わせただけで規格から導けない、といった場合は登録しない。
- 違法系（kind=error）の要求は、:should_fail_because: 付きの負テストが意図した規格違反の診断を照合している場合だけ。未対応構文のエラーを規格違反の検出と読み替えない。
- recommendation / implementation_defined / permission の要求は、テストがその選択や許可の観測可能な結果を確かめている場合だけ。
- 既存の保留（HELD）、20%監査で取り下げた組（WITHDRAWN）、BLOCKEDのテストは道具が拒否する。その理由を回避しようとしない。
`

function matcherPrompt(p) {
  return `あなたは IEEE 1800-2023 SystemVerilog 規格の要求台帳と、既存テストスイートの照合担当です（担当 ${p.label}）。
目的: 担当範囲の各未対応要求について、その節を :lrm: で引用している既存テストの中から、刺激と期待出力が要求全体を実際に検証しているものを見つけ、照合案として登録する。件数より正確さを優先し、不確かなら登録しない。後で独立した検証者が全件を反証しようとし、根拠の弱い案は却下される。
${COMMON_RULES}
あなた専用の追加コマンド（OUT=${p.out}）:
  python3 ${KIT} scope ${p.assign} --out ${p.out}     担当要求の一覧と進捗（open / open+check など）
  python3 ${KIT} add   --out ${p.out} <<'JSON' ... JSON   照合案（検査に失敗すると REJECTED と理由を表示）
  python3 ${KIT} group --out ${p.out} <<'JSON' ... JSON   AND集合案
  python3 ${KIT} hold  --out ${p.out} <<'JSON' ... JSON   保留判断（任意）
${CRITERIA}
進め方:
1. scope で一覧を確認し、節ごとに処理する。節の本文を requirement_source.py --show で読み、表のセルや例外・エラー条件も確認する。
2. 要求ごとに req で候補テストを見る。候補が多ければ grep で要求の条件に対応する構文・値・API名を含むテストに絞る。
3. 有望なテストは .sv 本体、C helper（:vpi_c: / :dpi_c:）、include、期待出力（.expected）まで読む。
4. 基準を満たせば add する。テストを読んだら、test サブコマンドでそのテストの他の未対応候補も確認し、同時に判断してよい（担当範囲外の要求でもよい）。
5. 照合案は見つけた時点ですぐ add する（文脈が要約されても成果が残る）。再開時は scope --out で進捗を確認する。担当範囲の全要求を一通り判断するまで続ける。1要求に時間をかけすぎず、見つからなければ次へ進む。

add の JSON:
{"requirement_id": "...", "test": "tests/chN/test_x.sv",
 "observation": "刺激と、比較している期待値を具体的に（日本語、1〜2文）",
 "rationale": "どんな誤実装で、どの期待出力がどう変わるか（日本語、具体値）",
 "evidence": [{"file": "tests/chN/test_x.sv", "contains": "<その条件を起こす行。ファイル中に完全一致で存在>"},
              {"file": "tests/chN/test_x.expected", "contains": "<その結果を示す期待出力。完全一致で存在>"},
              {"file": "tests/chN/test_x.c", "contains": "<C helperがあれば判定に使う箇所>"}]}
contains は改行を含めてよい。anchor は条件・結果に直接関係する文字列にする（module 行などの無関係な文字列にしない）。
期待出力がテスト本体内にある場合（:expected_stdout: が @ で始まらない）は .sv 内の anchor で代替される。

group の JSON:
{"requirement_id": "...", "group_id": "英数字と-_.", "collective_observation": "全メンバーで何がそろうか", "rationale": "...",
 "members": [{"test": "...", "observation": "...", "evidence": [...]}, ...]}

hold の JSON（任意。見送った理由が後の作業者に役立つ具体的な問題、特に期待値やテストの合法性の問題の場合だけ）:
{"test": "...", "requirement_ids": ["..."], "disposition": "partial_observation|oracle_issue|citation_refinement|compound_requirement",
 "explanation": "何が観測されていないか、または期待値の何が問題か（日本語、具体的に）", "evidence": [{"file": "<test>", "contains": "..."}]}

最後に、処理した要求数、add/group/hold の件数、気づいた系統的な問題を返す。`
}

function verifierPrompt(p) {
  return `あなたは照合案の独立検証者です（担当 ${p.label}）。別の担当者が作った照合案が、本当に要求全体を検証しているかを反証しようとしてください。照合案の observation / rationale を鵜呑みにせず、規格本文とテストを自分で読んで判断します。
照合案ファイル: ${p.out}
${COMMON_RULES}
あなた専用の追加コマンド:
  python3 ${KIT} show --out ${p.out}                          照合案のキーと判定状況の一覧
  照合案の全文は ${p.out} を直接読む（1行1件の JSON）。
  python3 ${KIT} verdict --out ${p.out} --key '<key>' --accept --reason '<理由>' --verifier '${p.label}-verifier'
  python3 ${KIT} verdict --out ${p.out} --key '<key>' --reject --reason '<理由>' --verifier '${p.label}-verifier'
${CRITERIA}
各照合案（type=check / group）について:
1. req で要求の behavior / acceptance / 出典を読み、requirement_source.py --show で該当ブロックの本文を読む。
2. テストの .sv、C helper、include、期待出力を自分で読む。
3. 次のどれかに当たれば reject する:
 - 刺激が要求の条件を起こしていない、または独立した条件の一部しか起こしていない（複合要求の部分観測）。
 - 期待出力が結果を区別しない（誤実装でも同じ出力になる）。rationale の誤実装例が実際には出力を変えない場合や、他のもっともらしい誤実装を見逃す場合も検討する。
 - 期待値が規格から導けない、規格と矛盾する、または正常系テストが違法な構文を含む。
 - anchor が刺激・判定に無関係な文字列。
 - 違法系なのに、意図した違反の診断を照合していない。
 - group で、メンバー全体でも要求の全条件がそろわない。
 不確かなら reject する。
4. type=hold は、explanation が具体的で、テストを読んで正しいと確認できれば accept、曖昧・誤りなら reject する。
5. すべての照合案に verdict を記録する（理由は日本語で具体的に）。show で [no verdict] と [stale: ...] が残っていないことを最後に確認する。accept は照合案・テスト入力・要求の承認時ハッシュを記録する。古い承認や変更済みの入力は、現行の内容を独立に再レビューしてから再承認する。

最後に accept / reject の件数と、主な reject 理由の傾向を返す。`
}

const MATCH_SCHEMA = {
  type: 'object',
  properties: {
    processed_requirements: { type: 'integer' },
    checks: { type: 'integer' },
    groups: { type: 'integer' },
    holds: { type: 'integer' },
    notes: { type: 'string' },
  },
  required: ['processed_requirements', 'checks', 'groups', 'holds', 'notes'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    accepted: { type: 'integer' },
    rejected: { type: 'integer' },
    unverdicted: { type: 'integer' },
    rejection_patterns: { type: 'string' },
  },
  required: ['accepted', 'rejected', 'unverdicted', 'rejection_patterns'],
}

const parts = args.labels.map(label => ({
  label,
  assign: `${WORK}/assign/${label}.json`,
  out: `${WORK}/proposals/${args.wave}/${label}.jsonl`,
}))

const results = await pipeline(
  parts,
  p => agent(matcherPrompt(p), { label: `match:${p.label}`, phase: 'Match', schema: MATCH_SCHEMA }),
  (m, p) => agent(verifierPrompt(p), { label: `verify:${p.label}`, phase: 'Verify', schema: VERIFY_SCHEMA })
    .then(v => ({ label: p.label, match: m, verify: v })),
)
return results
