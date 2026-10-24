export const meta = {
  name: 'interpretation-issue-review',
  description: 'Propose resolutions for the 46 open interpretation issues of the IEEE 1800-2023 requirement ledger, then independently challenge each proposal',
  phases: [
    { title: 'Analyze', detail: 'three analysts propose a decision per issue' },
    { title: 'Verify', detail: 'independent verifier per batch' },
  ],
}
// Arguments (Workflow args): repo = repository root, work = work directory
// with assign/, proposals/ and notes/, pdf = the IEEE 1800-2023 PDF,
// iverilogBin = bin directory of Icarus Verilog 13.0 (optional), and here
// batches = the open issues split into groups for the analysts.
// See tools/matching_kit/README.md.
const REPO = args.repo
const WORK = args.work
const PDF = args.pdf
const KIT = `${REPO}/tools/matching_kit/propose.py`
const RUNSIM = `${REPO}/tools/matching_kit/runsim.py${args.iverilogBin ? ` --iverilog-bin ${args.iverilogBin}` : ''}`
const COMMON = `
作業場所: ${REPO}（リポジトリルートで実行）。リポジトリ内のファイルは一切変更しない（台帳の編集はコーディネータが行う）。git 操作もしない。規格本文を長く引用しない（要点を自分の言葉で書き、節番号とブロックIDで示す）。
資料:
- 要求台帳 coverage/behaviors.json の interpretation_issue を持つ行（論点名は interpretation_issue のコロンより前）。
- 論点ごとの経緯: docs/requirement-extraction-notes.md（出典・関連・未解決点・解決条件）。
- 規格本文: python3 tools/requirement_source.py --show <節> [...]（ブロックID付き）。図表は PDF ${PDF} を読んでよい。附属書 I/K/M のヘッダのソースも本文として参照できる。
解消の基準（重要）: 手元にあるのは規格の PDF だけで、IEEE の公式な正誤表・解釈はない。規格の内部に決定的な根拠がある場合だけ「resolve」とする。例: 本文中の綴りが、規範的なヘッダ（附属書 I/K/M）や API・構文・表の定義と食い違い、定義側が一貫している場合。数式の添字の誤りが、同じ概念を定める本文（例: 16.9.3）と附属書の他の式から一意に復元できる場合。規範の記述どうしが実質的に衝突し、どちらを採っても他方を捨てることになる場合や、根拠が推測にとどまる場合は「keep」とし、何が決め手として欠けているかを書く。都合のよい解釈を黙って選ばない。
`
const ANALYZE_SCHEMA = {
  type: 'object',
  properties: {
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          issue: { type: 'string' },
          decision: { type: 'string', enum: ['resolve', 'keep'] },
          rationale_ja: { type: 'string', description: '判断の根拠（日本語）。参照した節とブロックIDを含める。' },
          adopted_interpretation_ja: { type: 'string', description: 'resolve のとき採用する解釈（日本語、1〜3文）。keep のとき空文字。' },
          missing_ja: { type: 'string', description: 'keep のとき、決め手として欠けているもの（日本語）。resolve のとき空文字。' },
          rows: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                behavior: { type: 'string', description: 'resolve のとき、採用した解釈で書き直した behavior（英語、既存行の文体）。keep のとき現状のまま。' },
                acceptance: { type: 'string', description: '同上の acceptance（英語）。観測可能な合格基準にする。' },
                kind: { type: 'string', enum: ['normal', 'error', 'boundary'] },
              },
              required: ['id', 'behavior', 'acceptance', 'kind'],
            },
          },
          section_review_note: { type: 'string', description: 'resolve のとき、節を閉じる review_note（英語、既存の書き方に合わせ1〜2文、採用した解釈と根拠を含む）。keep のとき空文字。' },
        },
        required: ['issue', 'decision', 'rationale_ja', 'adopted_interpretation_ja', 'missing_ja', 'rows', 'section_review_note'],
      },
    },
  },
  required: ['issues'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          issue: { type: 'string' },
          verdict: { type: 'string', enum: ['accept', 'reject'] },
          reason_ja: { type: 'string' },
        },
        required: ['issue', 'verdict', 'reason_ja'],
      },
    },
  },
  required: ['verdicts'],
}
// args.batches = [{label, issues: [issue names, as before the colon of interpretation_issue]}]
const batches = args.batches
function analyzePrompt(b) {
  return `あなたは IEEE 1800-2023 要求台帳の解釈保留を見直す分析担当です（束 ${b.label}）。担当する論点: ${b.issues.join(', ')}。
${COMMON}
各論点について、台帳の該当行（interpretation_issue が論点名で始まる全行）と notes の記述を読み、関係する節の本文（双方の出典ブロック、参照先、ヘッダ・表・構文）を自分で読んで、resolve か keep かを判断する。
resolve の場合: 採用する解釈、根拠（節とブロックID）、該当行ごとに書き直した behavior / acceptance（英語、既存行の文体、テストで観測できる合格基準）、kind（原則は現状のまま。変える場合は根拠を rationale に書く）、節を閉じる review_note を返す。要求の意味を弱めたり、元の記述にない義務を足したりしない。
keep の場合: 何が決め手として欠けているかを書き、rows は現状の behavior / acceptance / kind をそのまま返す。
担当の全論点を返す。`
}
function verifyPrompt(b, a) {
  return `あなたは解釈保留の解消案を反証する独立検証者です（束 ${b.label}）。分析担当の出力（JSON）は次のとおりです:
${JSON.stringify(a)}
${COMMON}
decision が resolve の各論点について、関係する節の本文を自分で読み、次のどれかに当たれば reject する: 規格内部の根拠が決定的でない（推測、または衝突する規範の一方を捨てている）／採用した解釈が本文と合わない／書き直した behavior / acceptance が元の要求を弱めた・義務を足した・観測できない／kind の変更に根拠がない／review_note が不正確。不確かなら reject。decision が keep の論点は、keep が妥当なら accept、実は決定的な根拠で resolve できる（あるいは keep の理由が誤り）なら reject とし理由に書く。
全論点に verdict を返す。`
}
return await pipeline(
  batches,
  b => agent(analyzePrompt(b), { label: `analyze:${b.label}`, phase: 'Analyze', schema: ANALYZE_SCHEMA }),
  (a, b) => agent(verifyPrompt(b, a), { label: `verify:${b.label}`, phase: 'Verify', schema: VERIFY_SCHEMA })
    .then(v => ({ label: b.label, analysis: a, verify: v })),
)
