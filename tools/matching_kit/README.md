# Matching kit

Tools to link IEEE 1800-2023 requirements (`coverage/behaviors.json`) to
tests by proposal, independent verdict and merge, as described in
[the method from the PDF to tests](../../docs/case-study-ieee1800/requirements-to-tests-method.md).
The repository is only read until `merge.py` applies accepted proposals; the
proposals, verdicts and notes live in a work directory outside it.

Local revision (2026-10-26): accepted proposals are bound to reviewed input
snapshots, with regression tests for stale approvals.

| File | What it does |
| --- | --- |
| `partition.py OUT_DIR` | Splits the open requirements into assignment files: `p..` (some test cites them; match first), `g..`, `a..`, `h..` (no candidate test; new tests needed) |
| `propose.py` | `scope`, `req`, `test` to read; `add`, `group`, `hold` to propose (checked at once with the conditions of `behavior_coverage.validate()`); `show`, `verdict`, `testverdict` for the verifier |
| `merge.py DIR --reviewer TEXT --date YYYY-MM-DD` | Applies the proposals whose latest verdict is `accept`, after checking them again; idempotent; `--dry-run` |
| `runsim.py tests/...` | Runs tests with Icarus Verilog 13.0 and Verilator 5.052 (seeds 1 and 73) and says which match, to decide `:oracle:` |
| `withdrawn-20261023.json` | Links withdrawn by the final audit of the 20% matching, which `propose.py` refuses |
| `workflows/match.js` | Claude Code Workflow: one matcher and one verifier per partition |
| `workflows/gap.js` | Claude Code Workflow: one writer (new tests, or matching first in `combined` mode) and one verifier per partition |
| `workflows/interpretation-review.js` | Claude Code Workflow: analysts propose resolutions of interpretation issues, verifiers challenge them |

## Work directory

```text
<work>/
  assign/<label>.json                 partition.py output
  proposals/<wave>/<label>.jsonl      proposals (one JSON object per line)
  proposals/<wave>/<label>.jsonl.verdicts.jsonl
  notes/<label>-tests.txt             new tests a writer made
  notes/<label>-testverdicts.jsonl    the verifier's ok/defective per new test
  notes/<label>-simdiff.md            simulator differences a writer found
```

## Proposal records

A check (`propose.py add --out FILE`, JSON on standard input):

```json
{"requirement_id": "SV2023-...", "test": "tests/chN/test_x.sv",
 "observation": "the stimulus and the values the expected output compares",
 "rationale": "which wrong implementation changes which output line, and how",
 "evidence": [{"file": "tests/chN/test_x.sv", "contains": "<the line that causes the condition>"},
              {"file": "tests/chN/test_x.expected", "contains": "<the output that shows the result>"}]}
```

An error-kind requirement needs a test with `:should_fail_because:`, and one
anchor that contains its `:expected_stderr_regex:` line instead of the
expected output. A group (`group`) has `group_id`, `collective_observation`,
`rationale` and `members`, each a test with `observation` and `evidence`. A
hold (`hold`) has `test`, `requirement_ids`, `disposition`
(`partial_observation`, `oracle_issue`, `citation_refinement`,
`compound_requirement`), `explanation` and `evidence`.

## Workflows

An `accept` verdict records SHA-256 identities for the proposal, every member
test's inputs (including expected output and helpers), and every related
requirement's content and source references. `show` marks an acceptance as
`[stale: ...]` if those inputs change or the verdict predates this snapshot
format. Independently review the current inputs before recording another
`verdict --accept`; the command records the version, not the semantic review.
Rejected verdicts do not require a snapshot.

Before writing, `merge.py` checks all unapplied accepted proposals and their
snapshots. If any fails, it exits with status 1 without changing either ledger
or the merge log, including with `--dry-run`. Existing unversioned acceptances
are not upgraded automatically. Already-applied entries remain idempotent;
the normal ledger checks still verify their stored input digests.

The scripts are inputs of the Workflow tool of Claude Code. Their prompts are
in Japanese and hold the review criteria. Typical arguments:

```js
{repo: "<repository root>", work: "<work directory>", pdf: "<the IEEE 1800-2023 PDF>",
 iverilogBin: "<Icarus Verilog 13.0>/bin",
 // match.js
 wave: "wave1", labels: ["p01-...", "p02-..."],
 // gap.js
 parts: [{label: "p01-...", wave: "wave1", mode: "gap" | "combined" | "annexA"}],
 verifyOnly: false, resume: false,
 // interpretation-review.js
 batches: [{label: "A", issues: ["ISSUE-NAME", ...]}]}
```

After the verifiers finish, merge, then regenerate and check as in section 9
of the method.
