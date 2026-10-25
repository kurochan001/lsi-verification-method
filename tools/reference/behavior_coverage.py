#!/usr/bin/env python3
"""Measure reviewed IEEE 1800-2023 behavior obligations, separately from citations.

    python3 tools/behavior_coverage.py --update
    python3 tools/behavior_coverage.py --check
    python3 tools/behavior_coverage.py --results results/*.json --output /tmp/behavior.md
    python3 tools/behavior_coverage.py --require-complete

The whole-standard percentage is unknown until every normative section's own
text (including parent introductions and annexes) has been decomposed/reviewed.
Registered obligations and current execution evidence have separate denominators.
No requirement is inferred from :lrm:, a test name, :oracle: or a simulator pass.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import suite_results

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "coverage"
REPORT = ROOT / "docs" / "behavior-coverage.md"
SUMMARY_REPORT = ROOT / "docs" / "behavior-coverage-summary.md"
SUMMARY_JSON = DATA / "behavior-summary.json"
METRIC_POLICY_VERSION = 3
OUTCOME_PRIORITY = ("pass", "fail", "known", "unsupported", "unreviewed_oracle", "stale", "not_run")
REVIEWS = {"unreviewed", "in_progress", "complete", "no_behavior"}
KINDS = {"normal", "boundary", "error"}
SIMULATORS = {"icarus", "verilator", "kirimasim", "lyra"}


class InvalidCoverage(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidCoverage(message)


def section_key(number: str) -> tuple:
    parts = number.split(".")
    first = int(parts[0]) if parts[0].isdigit() else 100 + ord(parts[0])
    return first, *(int(p) for p in parts[1:])


def local_file(name: str) -> Path:
    require(isinstance(name, str) and name, "empty file reference")
    path = (ROOT / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(ROOT),
            f"file outside repository: {name}")
    require(path.is_file(), f"missing file: {name}")
    return path


def validate(inventory: dict, registry: dict) -> tuple[dict, list]:
    """Reject malformed/stale links; an intentionally unmapped obligation is valid."""
    require(inventory.get("schema") == registry.get("schema") == 1, "unknown schema")
    denominator = registry.get("denominator_review", {"state": "pending"})
    require(denominator.get("state") in ("pending", "approved"), "invalid denominator review")
    if denominator["state"] == "approved":
        require(all(denominator.get(k) for k in ("reviewer", "reviewed_on", "scope_note")),
                "approved denominator needs review metadata")
    sections = {}
    for s in inventory["sections"]:
        number = s["id"]
        require(re.fullmatch(r"(?:[1-9]|[1-3][0-9]|4[01]|[A-Q])(?:\.[1-9][0-9]*)*",
                             number), f"invalid section {number}")
        require(number not in sections, f"duplicate section {number}")
        require(s.get("title") and isinstance(s.get("pdf_page"), int)
                and 1 <= s["pdf_page"] <= inventory["source"]["pdf_pages"],
                f"invalid source location {number}")
        require(s.get("kind") in ("normative", "informative"), f"invalid kind {number}")
        require(s.get("review") in REVIEWS, f"invalid review {number}")
        if s["review"] in ("complete", "no_behavior"):
            require(s.get("review_note") and s.get("reviewed_on"),
                    f"completed audit needs a rationale/date: {number}")
        sections[number] = s
    roots = {str(n) for n in range(1, 42)} | set("ABCDEFGHIJKLMNOPQ")
    require(roots <= sections.keys(), "inventory must include clauses 1–41 and annexes A–Q")
    for number in sections:
        if "." in number:
            require(number.rsplit(".", 1)[0] in sections, f"missing parent of {number}")
    # The baseline locks the imported section set as well as registered IDs.
    rows, ids = [], set()
    digest_cache = {}
    for r in registry["requirements"]:
        rid = r["id"]
        require(re.fullmatch(r"SV2023-[A-Z0-9.-]+", rid), f"invalid behavior ID {rid}")
        require(rid not in ids, f"duplicate behavior ID {rid}")
        ids.add(rid)
        require(r.get("clause") in sections, f"unknown clause: {rid}")
        require(sections[r["clause"]]["kind"] == "normative", f"informative behavior: {rid}")
        require(sections[r["clause"]]["review"] != "no_behavior",
                f"no_behavior section has a requirement: {rid}")
        require(r.get("kind") in KINDS, f"invalid case kind: {rid}")
        require(all(isinstance(r.get(k), str) and r[k].strip()
                    for k in ("behavior", "acceptance", "source_note")),
                f"behavior, acceptance and source_note required: {rid}")
        checks, seen = [], set()
        for c in r["checks"]:
            test = local_file(c["test"])
            require(test in suite_test_paths(), f"not a suite test: {c['test']}")
            require(c["test"] not in seen, f"duplicate test mapping: {rid}")
            seen.add(c["test"])
            fields = suite_results.header(test)
            require(r["clause"] in fields.get("lrm", "").split()[1:],
                    f"test must cite mapped clause {r['clause']}: {c['test']}")
            require(bool(fields.get("should_fail_because")) == (r["kind"] == "error"),
                    f"negative/positive case mismatch: {rid}")
            require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", c.get("reviewed_on", ""))
                    and c.get("reviewer") and c.get("observation"),
                    f"mapping needs review date, reviewer and observation: {rid}")
            if test not in digest_cache:
                digest_cache[test] = suite_results.input_digest(test)
            require(c.get("inputs_sha256") == digest_cache[test],
                    f"stale reviewed mapping: {rid} -> {c['test']}; review changed inputs")
            inputs = set(suite_results.input_files(test))
            anchors = c.get("evidence", [])
            require(anchors and any(a["file"] == c["test"] for a in anchors),
                    f"mapping must identify a stimulus in the test: {rid}")
            expected = fields.get("expected_stdout", "")
            expected_path = (test.parent / expected[1:]).resolve() if expected.startswith("@") else test
            require(any(local_file(a["file"]) == expected_path for a in anchors)
                    if r["kind"] != "error" else
                    any("expected_stderr_regex" in a["contains"] for a in anchors),
                    f"mapping must identify the checked output/diagnostic: {rid}")
            for a in anchors:
                path = local_file(a["file"])
                require(path in inputs, f"evidence not among test inputs: {a['file']}")
                require(a.get("contains") and a["contains"] in path.read_text(encoding="utf-8"),
                        f"missing observation anchor: {rid} in {a['file']}")
            checks.append(c)
        groups = r.get("check_groups", [])
        require(isinstance(groups, list), f"invalid check groups: {rid}")
        if groups:
            group_ids, members = set(), set()
            for group in groups:
                require(isinstance(group.get("id"), str)
                        and re.fullmatch(r"[A-Za-z0-9_.-]+", group["id"])
                        and group["id"] not in group_ids,
                        f"duplicate/empty check group: {rid}")
                group_ids.add(group["id"])
                require(group.get("reviewer") and group.get("observation")
                        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", group.get("reviewed_on", "")),
                        f"check group needs collective review: {rid}")
                tests = group.get("tests", [])
                require(isinstance(tests, list) and tests and len(tests) == len(set(tests))
                        and set(tests) <= seen, f"unknown/duplicate check group member: {rid}")
                members.update(tests)
            require(members == seen, f"check group leaves an ungrouped test: {rid}")
        rows.append({**r, "mapped": bool(checks)})
    for number, s in sections.items():
        if s["review"] == "complete":
            require(any(r["clause"] == number for r in rows),
                    f"complete section has no decomposed obligations: {number}")
    return sections, rows


_test_paths = None


def suite_test_paths() -> set:
    global _test_paths
    if _test_paths is None:
        _test_paths = set(suite_results.find_tests())
    return _test_paths


def baseline(sections: dict, rows: list, source: dict | None = None) -> dict:
    structure = [{k: s[k] for k in ("id", "title", "pdf_page", "kind")}
                 for _, s in sorted(sections.items(), key=lambda item: section_key(item[0]))]
    return {"schema": 1,
            "inventory_sha256": hashlib.sha256(json.dumps(
                [source, structure], sort_keys=True).encode()).hexdigest(),
            "sections": sorted(sections, key=section_key),
            "normative_sections": sorted((n for n, s in sections.items()
                                           if s["kind"] == "normative"), key=section_key),
            "requirements": sorted(r["id"] for r in rows),
            "contracts": {r["id"]: hashlib.sha256(json.dumps(
                {k: r[k] for k in ("clause", "kind", "behavior", "acceptance", "source_note")},
                sort_keys=True).encode()).hexdigest() for r in rows},
            "witness_groups": {r["id"]: hashlib.sha256(json.dumps(
                {"groups": r["check_groups"], "checks": r["checks"]},
                sort_keys=True).encode()).hexdigest() for r in rows if r.get("check_groups")},
            "mapped": sorted(r["id"] for r in rows if r["mapped"]),
            "audited_sections": sorted((n for n, s in sections.items()
                                        if s["review"] in ("complete", "no_behavior")),
                                       key=section_key)}


def check_baseline(before: dict, after: dict) -> None:
    require(before.get("schema") == 1, "unknown baseline schema")
    require(before["inventory_sha256"] == after["inventory_sha256"],
            "standard inventory/source changed; review and explain a baseline update")
    if "source_index_sha256" in before:
        require(before["source_index_sha256"] == after.get("source_index_sha256"),
                "source-block inventory changed; reconcile the PDF/text and explain a baseline update")
    if "source_reviewed_sections" in before:
        require(set(before["source_reviewed_sections"]) <= set(after.get("source_reviewed_sections", [])),
                "source review regression: previously classified sections are missing")
    for key in ("sections", "normative_sections", "requirements", "mapped", "audited_sections"):
        lost = set(before[key]) - set(after[key])
        require(not lost, f"coverage regression ({key}): {', '.join(sorted(lost))}")
    for rid, digest in before["contracts"].items():
        require(after["contracts"].get(rid) == digest,
                f"behavior contract changed: {rid}; review and explain a baseline update")
    for rid, digest in before.get("witness_groups", {}).items():
        require(after.get("witness_groups", {}).get(rid) == digest,
                f"collective witness changed: {rid}; review and explain a baseline update")


def execution(rows: list, result_paths: list[Path]) -> tuple[dict, list]:
    """Only fresh pass results count. Files are separate snapshots, never merged
    across versions/runs to make a single simulator appear to cover more cases.
    """
    snapshots, ignored = [], []
    digests = {}
    for path in sorted(result_paths):
        data = json.loads(path.read_text(encoding="utf-8"))
        simulator = data.get("simulator")
        if (simulator not in SIMULATORS or not data.get("version")
                or not data.get("generated_at") or data.get("runner_changed")
                or data.get("runner_sha256") != suite_results.runner_digest(simulator)):
            ignored.append(f"{path.name}: legacy, unknown, or stale runner provenance")
            continue
        executed, stale, outcomes = set(), 0, {}
        for r in rows:
            if r.get("interpretation_issue"):
                outcomes[r["id"]] = "interpretation_pending"
                continue
            if not r["mapped"]:
                outcomes[r["id"]] = "unmapped"
                continue
            by_test = {}
            for c in r["checks"]:
                test = ROOT / c["test"]
                result = data.get("tests", {}).get(suite_results.test_id(test), {})
                if not result:
                    by_test[c["test"]] = "not_run"
                    continue
                if c["test"] not in digests:
                    digests[c["test"]] = suite_results.input_digest(test)
                if (result.get("inputs_changed")
                        or result.get("inputs_sha256") != digests[c["test"]]):
                    stale += 1
                    by_test[c["test"]] = "stale"
                    continue
                if result.get("status") != "pass":
                    by_test[c["test"]] = (result["status"] if result.get("status") in
                                           ("fail", "known", "unsupported") else "not_run")
                    continue
                # Unsupported syntax can accidentally satisfy an illegal-test
                # line regexp. Only a reviewed, pinned negative oracle counts.
                if r["kind"] == "error":
                    oracle = {"icarus": ("iverilog@13.0", r"version 13\.0(?:\s|$)"),
                              "verilator": ("verilator@5.052", r"Verilator 5\.052(?:\s|$)")}
                    token, version = oracle.get(simulator, ("", r"(?!)"))
                    if (token not in suite_results.header(test).get("oracle", "").split()
                            or not re.search(version, data["version"])):
                        by_test[c["test"]] = "unreviewed_oracle"
                        continue
                by_test[c["test"]] = "pass"
            groups = ([g["tests"] for g in r["check_groups"]] if r.get("check_groups")
                      else [[c["test"]] for c in r["checks"]])
            observed = set()
            for group in groups:
                states = {by_test[name] for name in group}
                observed.add("pass" if states == {"pass"} else
                             next(s for s in OUTCOME_PRIORITY[1:] if s in states))
            outcomes[r["id"]] = next((s for s in OUTCOME_PRIORITY if s in observed), "not_run")
            if outcomes[r["id"]] == "pass":
                executed.add(r["id"])
        snapshots.append({"file": path.name, "simulator": simulator,
                          "version": data["version"], "generated_at": data["generated_at"],
                          "executed": sorted(executed), "stale_links": stale,
                          "outcomes": outcomes,
                          "status_counts": {s: sum(v == s for v in outcomes.values())
                                            for s in (*OUTCOME_PRIORITY, "unmapped", "interpretation_pending")}})
    return {"snapshots": snapshots,
            "executed": sorted({rid for s in snapshots for rid in s["executed"]})}, ignored


def summarize(sections: dict, rows: list, runs: dict, denominator_reviewed: bool = False) -> dict:
    normative = {n: s for n, s in sections.items() if s["kind"] == "normative"}
    audited = sum(s["review"] in ("complete", "no_behavior") for s in normative.values())
    mapped = sum(r["mapped"] for r in rows)
    total_known = denominator_reviewed and audited == len(normative) and bool(rows)
    return {"sections": len(sections), "normative_sections": len(normative),
            "audited_sections": audited, "registered": len(rows), "mapped": mapped,
            "denominator_reviewed": denominator_reviewed,
            "extraction_progress_percent": 100 * audited / len(normative) if normative else None,
            "unmapped": len(rows) - mapped, "executed": len(runs["executed"]),
            "whole_standard_percent": 100 * mapped / len(rows) if total_known else None,
            "whole_standard_executed_percent": 100 * len(runs["executed"]) / len(rows)
            if total_known else None,
            "registered_percent": 100 * mapped / len(rows) if rows else None}


def measurement(sections: dict, rows: list, runs: dict, source_audit: dict,
                denominator_reviewed: bool, inventory_sha256: str) -> dict:
    """Publish a provisional full-inventory metric without certifying its units.

    Every registered row remains in the denominator, including interpretation
    holds and unmapped rows. Partial source extraction never becomes a full-scope
    provisional percentage. The denominator identity excludes test mappings and
    run outcomes so ordinary testing progress remains comparable over time.
    """
    stats = summarize(sections, rows, runs, denominator_reviewed)
    complete_source = source_audit["source_review_complete"]
    executed = set(runs["executed"])
    partition = {"pass": 0, "mapped_without_pass": 0, "unmapped": 0, "interpretation_pending": 0}
    chapters = []
    for r in rows:
        partition[requirement_status(r, executed)] += 1
    for root in sorted((n for n in sections if "." not in n), key=section_key):
        group = [r for r in rows if r["clause"].split(".")[0] == root]
        total = len(group)
        mapped = sum(r["mapped"] for r in group)
        passed = sum(r["id"] in executed for r in group)
        chapters.append({"clause": root, "title": sections[root]["title"],
                         "registered": total, "mapped": mapped, "executed": passed,
                         "design_percent": 100 * mapped / total if total else None,
                         "execution_percent": 100 * passed / total if total else None,
                         "interpretation_pending": sum(bool(r.get("interpretation_issue")) for r in group)})
    identity = {"metric_policy_version": METRIC_POLICY_VERSION,
                "inventory_sha256": inventory_sha256,
                "contracts": baseline(sections, rows)["contracts"]}
    linked_tests = {check["test"] for row in rows for check in row["checks"]}
    suite_tests = {test.relative_to(ROOT).as_posix() for test in suite_results.find_tests()}
    return {"metric_policy_version": METRIC_POLICY_VERSION,
            "whole_standard_status": ("confirmed" if stats["whole_standard_percent"] is not None
                                      else "provisional" if complete_source else "source_incomplete"),
            "provisional_design_percent": stats["registered_percent"] if complete_source else None,
            "provisional_execution_percent": (100 * len(executed) / len(rows)
                                               if complete_source and rows else None),
            "denominator": {"count": len(rows), "unit": "registered_requirement_condition_or_observation",
                            "sha256": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                            "reviewed": denominator_reviewed, "source_review_complete": complete_source,
                            "interpretation_pending": partition["interpretation_pending"]},
            "test_mapping": {"suite_test_files": len(suite_tests),
                             "linked_test_files": len(linked_tests & suite_tests),
                             "unlinked_test_files": len(suite_tests - linked_tests)},
            "collective_requirement_count": sum(bool(r.get("check_groups")) for r in rows),
            "requirement_status_counts": partition, "chapters": chapters}


def requirement_status(row: dict, executed: set) -> str:
    if row.get("interpretation_issue"):
        return "interpretation_pending"
    if not row["mapped"]:
        return "unmapped"
    return "pass" if row["id"] in executed else "mapped_without_pass"


def compact_report(snapshot: dict, source_url: str | None = None,
                   detailed_report: str = "behavior-coverage.md") -> str:
    """A small, generated entry point; the full report retains each obligation."""
    def percent(value):
        return "未確定" if value is None else f"{value:.2f}%"
    def ratio(count, total):
        return f"{count}/{total} ({100 * count / total:.2f}%)" if total else "対象項目なし"
    link = lambda p: f"{source_url.rstrip('/')}/{p}" if source_url else f"../{p}"
    total = snapshot["registered"]
    counts = snapshot["requirement_status_counts"]
    scope = snapshot["denominator"]
    test_mapping = snapshot["test_mapping"]
    lines = ["# IEEE 1800-2023 動作カバレッジ集計", "",
             f"[全項目の詳細]({detailed_report}) / "
             f"[管理手順]({link('coverage/README.md')}) / "
             f"[解釈保留の根拠]({link('docs/requirement-extraction-notes.md')})", "",
             "## 全規格の要求台帳に対する暫定値", "",
             f"- テスト設計網羅率: **{percent(snapshot['provisional_design_percent'])}** "
             f"({snapshot['mapped']}/{total})。",
             f"- 実行確認率: **{percent(snapshot['provisional_execution_percent'])}** "
             f"({snapshot['executed']}/{total})。複数環境の成功の和集合。",
             "- 分母には解釈保留と未対応も含みます。未実装・未対応を除外していません。",
             "- 登録単位は要求の出現箇所・条件・初期の観測ケースであり、意味の重複整理前の暫定値です。",
             "  全プログラム・全入力の組み合わせを試した割合や、単一シミュレータの規格適合率ではありません。", "",
             "## 既存テストの集計状況", "",
             f"- 全 {test_mapping['suite_test_files']} 本のうち、要求との対応を登録済みのテストは "
             f"{test_mapping['linked_test_files']} 本。未登録は {test_mapping['unlinked_test_files']} 本です。",
             "- 上記の網羅率は、刺激と期待結果を確認して要求との対応を登録した分だけを計上しています。",
             "  未登録の既存テストも検証に役立ちますが、その貢献はまだ割合に反映できていません。",
             "- 登録済み本数は少なくとも一つの要求との対応がある本数で、テスト全体のレビュー完了数ではありません。", "",
             f"- 複数テストで分担する要求は {snapshot['collective_requirement_count']} 行。"
             "各グループの全テストが同じ実行回で成功した場合だけ、要求全体の実行成功に数えます。", "",
             "## 確定値", "",
             f"- 規格全動作のテスト設計網羅率: {percent(snapshot['whole_standard_percent'])}。",
             f"- 規格全動作の実行確認率: {percent(snapshot['whole_standard_executed_percent'])}。",
             f"- 分母の承認: {'承認済み' if scope['reviewed'] else '未承認'}。"
             f"計測状態: `{snapshot['whole_standard_status']}`。",
             "- 資料確認、保留解釈の解決、要求単位の重複整理、分母のレビューを経て確定します。", "",
             "## 残件", "",
             f"- 新鮮な成功証跡あり: {counts['pass']} 行。",
             f"- 対応済み・成功証跡なし: {counts['mapped_without_pass']} 行。",
             f"- テスト対応未確認（解釈保留以外）: {counts['unmapped']} 行。",
             f"- 解釈保留: {counts['interpretation_pending']} 行。",
             "", "未対応は、既存テストが存在しないという判定ではありません。", "",
             "## シミュレータ別の実行確認率", ""]
    for run in snapshot["execution"]["snapshots"]:
        detail = run["status_counts"]
        lines += [f"- `{run['simulator']}` / {run['version']}: {ratio(len(run['executed']), total)}。",
                  f"  計測元: {run['generated_at']} / `{run['file']}`。",
                  f"  失敗 {detail['fail']}、既知不一致 {detail['known']}、未対応 {detail['unsupported']}、"
                  f"未実行 {detail['not_run']}、古い証跡 {detail['stale']}、"
                  f"違法系の判定根拠未承認 {detail['unreviewed_oracle']} 行。"]
    if not snapshot["execution"]["snapshots"]:
        lines.append("採用可能な実行証跡なし。")
    lines += [f"- 不採用の結果ファイル: {len(snapshot['ignored_results'])} 件。", "",
              "## 章・附属書別（登録項目に対する割合）", ""]
    for chapter in snapshot["chapters"]:
        lines.append(f"- {chapter['clause']} {chapter['title']}: "
                     f"設計 {ratio(chapter['mapped'], chapter['registered'])}、"
                     f"実行 {ratio(chapter['executed'], chapter['registered'])}、"
                     f"解釈保留 {chapter['interpretation_pending']} 行。")
    lines += ["", "## 分母と履歴", "",
              f"- 分母SHA-256: `{scope['sha256']}`。",
              f"- 計測規則の版: {snapshot['metric_policy_version']}。",
              "- 履歴には分母の識別子、暫定値と確定値、環境別の状態内訳を保存します。",
              "  分母が異なる回の割合を、そのまま改善・悪化として比較しません。",
              "- この集計は保存済み実行証跡から再生成されます。上記の計測元時刻が実行時刻です。"]
    return "\n".join(lines) + "\n"


def append_history(path: Path, entry: dict) -> None:
    """Keep the denominator identity beside counts so scope changes stay visible."""
    data = json.loads(path.read_text()) if path.is_file() else {"schema": 1, "runs": []}
    require(data.get("schema") == 1 and isinstance(data.get("runs"), list),
            "unknown behavior history format")
    data["runs"].append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def summary_data(snapshot: dict, keep_timestamp: bool = False) -> dict:
    """Keep per-item outcomes in the detailed JSON, not every history entry."""
    result = {k: v for k, v in snapshot.items() if k != "generated_at" or keep_timestamp}
    result["execution"] = {"snapshots": [{k: v for k, v in run.items() if k != "outcomes"}
                                         for run in snapshot["execution"]["snapshots"]]}
    return result


def report(inventory: dict, sections: dict, rows: list, runs: dict, ignored: list,
           source_url: str | None = None, source_audit: dict | None = None,
           denominator_reviewed: bool = False, measured: dict | None = None) -> str:
    stats = summarize(sections, rows, runs, denominator_reviewed)
    total = stats["registered"]
    pct = lambda n: f"{n}/{total} ({100*n/total:.2f}%)" if total else "0/0 (undefined)"
    whole = stats["whole_standard_percent"]
    executed_whole = stats["whole_standard_executed_percent"]
    pending = ("未確定（資料確認済み。解釈保留と要求の重複整理が残る）"
               if source_audit and source_audit["source_review_complete"]
               else "未確定（要求の洗い出しが未完了）")
    link = lambda path: f"{source_url.rstrip('/')}/{path}" if source_url else f"../{path}"
    lines = ["# IEEE 1800-2023 動作カバレッジ", "",
             "`tools/behavior_coverage.py` が `coverage/` の台帳と実行証跡から生成します。",
             f"[集計概要]({link('docs/behavior-coverage-summary.md')}) / "
             f"[全要求の抽出結果]({link('docs/requirement-extraction.md')}) / "
             f"[管理手順]({link('coverage/README.md')}) / "
             f"[節の引用数]({link('docs/coverage-depth.md')})", "",
             f"**規格全動作のテスト設計網羅率: {pending if whole is None else f'{whole:.2f}%'}。**",
             f"規格全動作の実行確認率: {'未確定' if executed_whole is None else f'{executed_whole:.2f}%'}。",
             "節の引用やテスト本数を、全動作の網羅率に換算しません。", "",
             f"- 規格棚卸し: 本文1–41章と附属書A–Q、計 {stats['sections']} 見出し。",
             f"- 規定部分の解釈保留なし: {stats['audited_sections']}/{stats['normative_sections']} 見出し "
             f"({stats['extraction_progress_percent']:.2f}%)。資料確認率・動作網羅率とは別です。",
             f"- 登録済み動作に対するテスト設計網羅率: {pct(stats['mapped'])}。",
             f"- 登録済み動作のうち、新鮮な実行成功証跡があるもの: {pct(stats['executed'])}。",
             f"- 登録済みだがテスト未対応: {stats['unmapped']} 動作。", "",
             "登録済み動作だけの割合は規格全体の割合ではありません。親節の導入本文も独立した",
             "調査対象です。図・表・構文・例外・エラー・他節参照を調べ、要求を分解して初めて",
             "その見出しを完了にできます。ツール依存・未実装は自動的な除外理由になりません。", "",
             f"[要求抽出の未解決事項]({link('docs/requirement-extraction-notes.md')})も管理します。",
             "登録単位には要求文の出現箇所、条件別の検証項目、初期登録の具体的な観測ケースを含みます。",
             "登録件数は、意味的に重複のない全規格要求数を確定した値ではありません。", "",
             "## 実行証跡", "",
             "成功は対応テストの全期待出力／診断の一致を意味します。`known`、`unsupported`、",
             "`fail`、来歴なし、入力／ランナー変更後の結果は成功に数えません。複数の結果の和集合は",
             "独立した検証環境での確認数であり、一つのシミュレータの適合率ではありません。", ""]
    lines += ["複数テストで一つの要求を分担する `check_groups` は、同じ実行環境・実行回で",
              "グループ内の全テストが成功した場合に限り成功とします。未指定の対応は独立した代替証拠です。", ""]
    if measured:
        provisional = measured["provisional_design_percent"]
        execution_pct = measured["provisional_execution_percent"]
        display = lambda value: "未確定" if value is None else f"{value:.2f}%"
        lines[6:6] = [f"**全規格の要求台帳ベース（暫定）: 設計 {display(provisional)}、"
                      f"実行 {display(execution_pct)}。**",
                      "解釈保留・未対応を分母に含めます。意味の重複整理前の値で、以下の確定値とは区別します。", ""]
    if source_audit:
        position = lines.index(f"- 規格棚卸し: 本文1–41章と附属書A–Q、計 {stats['sections']} 見出し。") + 1
        lines[position:position] = [
            f"- 全資料の確認・要求抽出: {source_audit['audited']}/{source_audit['sections_total']} 節 "
            f"({source_audit['source_review_percent']:.2f}%)、"
            f"{source_audit['classified_blocks']}/{source_audit['blocks_total']} 出典ブロックを分類済み。",
            f"- 規定部分の資料確認: {source_audit['normative_reviewed']}/{stats['normative_sections']} 節 "
            f"({source_audit['normative_source_review_percent']:.2f}%)。",
            f"- 解釈保留: {source_audit['interpretation_issues']} 論点、"
            f"{len(source_audit['interpretation_sections'])} 節、"
            f"{source_audit['interpretation_issue_rows']} 登録行。保留を完了・テスト対応済みに数えません。",
        ]
    if not runs["snapshots"]:
        lines.append("採用可能な実行証跡なし。")
    for s in runs["snapshots"]:
        lines.append(f"- `{s['file']}`: {s['version']} / {s['generated_at']} / "
                     f"{len(s['executed'])}/{total} 動作確認、古い入力との対応 {s['stale_links']} 件。")
    for reason in ignored:
        lines.append(f"- 不採用: {reason}。")
    lines += ["", "## 章・附属書別の調査状態", "",
              "件数は見出しごとの本文の調査状態です。動作数とは異なります。", ""]
    for root in sorted((n for n in sections if "." not in n), key=section_key):
        group = [s for n, s in sections.items() if n == root or n.startswith(root + ".")]
        norm = [s for s in group if s["kind"] == "normative"]
        done = sum(s["review"] in ("complete", "no_behavior") for s in norm)
        rs = [r for r in rows if r["clause"].split(".")[0] == root]
        state = f"解釈保留なし {done}/{len(norm)}" if norm else "参考（規範要件の分母に含めない）"
        lines.append(f"- {root} {sections[root]['title']}: {state}、"
                     f"登録 {len(rs)}、テスト対応 {sum(r['mapped'] for r in rs)}。")
    lines += ["", "## 登録済み動作と観測点", "",
              "`coverage/behaviors.json` には条件・合格基準・根拠・入力ハッシュも記録します。",
              "以下の対応は内容を確認したものだけです。引用だけがあるテストは候補として扱います。", ""]
    lines += ["未対応は台帳上の対応未確認を意味し、既存テストが一切ないという判定ではありません。", ""]
    executed = set(runs["executed"])
    for r in sorted(rows, key=lambda r: (section_key(r["clause"]), r["id"])):
        state = "実行確認あり" if r["id"] in executed else "テスト対応あり・実行未確認" if r["mapped"] else "テスト未対応"
        lines += [f"### {r['id']}", "", f"{r['clause']} / {r['kind']} / {state}", "",
                  r["behavior"], "", f"合格基準: {r['acceptance']}", ""]
        if r.get("modality"):
            lines += [f"規定の性質: `{r['modality']}`。", ""]
        if r.get("interpretation_issue"):
            lines += [f"未解決の解釈: `{r['interpretation_issue']}`（対応承認・節完了を保留）。", ""]
        for c in r["checks"]:
            lines.append(f"- [{Path(c['test']).name}]({link(c['test'])}): {c['observation']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--update", action="store_true")
    modes.add_argument("--check", action="store_true")
    ap.add_argument("--results", type=Path, nargs="+", help="replace the saved execution snapshots")
    ap.add_argument("--output", type=Path, default=REPORT)
    ap.add_argument("--source-url", help="repository blob URL for links in an exported report")
    ap.add_argument("--json", type=Path, help="also write a machine-readable summary")
    ap.add_argument("--summary-output", type=Path, help="compact Markdown; defaults beside the standard report")
    ap.add_argument("--summary-json", type=Path, help="compact JSON; defaults to coverage/behavior-summary.json")
    ap.add_argument("--history", type=Path, help="append counts and denominator identities to history")
    ap.add_argument("--require-complete", action="store_true",
                    help="require an audited whole-standard denominator and all behaviors mapped/executed")
    ap.add_argument("--require-source-reviewed", action="store_true",
                    help="require classified source blocks for every section; does not approve interpretations or tests")
    ap.add_argument("--verify-source", type=Path, help="verify supplied PDF and extracted-text SHA-256")
    ap.add_argument("--test-digest", type=Path, help="print a test fingerprint after manual review")
    ap.add_argument("--candidates", help="list exact-citation test candidates for a section")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--reason", help="reason for an intentional baseline change")
    args = ap.parse_args()
    if args.test_digest:
        print(suite_results.input_digest(args.test_digest))
        return 0
    try:
        inventory = json.loads((DATA / "standard-sections.json").read_text())
        registry = json.loads((DATA / "behaviors.json").read_text())
        sections, rows = validate(inventory, registry)
        import requirement_audit
        audit_stats = requirement_audit.load_and_validate(DATA, inventory, registry)
        if args.candidates:
            require(args.candidates in sections, f"unknown section {args.candidates}")
            candidates = [{"test": t.relative_to(ROOT).as_posix(),
                           "description": suite_results.header(t).get("description", "")}
                          for t in suite_results.find_tests()
                          if args.candidates in suite_results.header(t).get("lrm", "").split()[1:]]
            print(json.dumps(candidates, ensure_ascii=False, indent=2))
            return 0
        current = baseline(sections, rows, inventory["source"])
        current["source_index_sha256"] = audit_stats["source_index_sha256"]
        current["source_reviewed_sections"] = sorted(
            json.loads((DATA / "requirement-audit.json").read_text())["sections"], key=section_key)
        if args.write_baseline:
            require(bool(args.reason and args.reason.strip()), "--write-baseline requires --reason")
            current["reason"] = args.reason
            (DATA / "behavior-baseline.json").write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        else:
            previous = json.loads((DATA / "behavior-baseline.json").read_text())
            check_baseline(previous, current)
            growth = any(previous.get(k) != value for k, value in current.items())
            if growth and args.update:
                (DATA / "behavior-baseline.json").write_text(json.dumps(
                    {**current, "reason": "Monotonic additions of requirements, mappings or "
                     "completed investigations, recorded by --update"},
                    ensure_ascii=False, indent=2) + "\n")
            if args.check:
                require(not growth, "baseline does not yet lock new coverage; run --update")
        if args.verify_source:
            source = inventory["source"]
            pdf = args.verify_source / source["pdf"]
            require(hashlib.sha256(pdf.read_bytes()).hexdigest() == source["pdf_sha256"],
                    "the PDF differs from the inventoried standard")
            source_index = json.loads((DATA / "requirement-source-index.json").read_text())
            layout = args.verify_source / "out/lrm_pdftotext_layout.txt"
            require(hashlib.sha256(layout.read_bytes()).hexdigest() == source_index["text_sha256"],
                    "the extracted text differs from the audited standard")
        runs, ignored = execution(rows, args.results if args.results is not None
                                  else list((DATA / "results").glob("*.json")))
        denominator_reviewed = registry.get("denominator_review", {}).get("state") == "approved"
        stats = summarize(sections, rows, runs, denominator_reviewed)
        measured = measurement(sections, rows, runs, audit_stats, denominator_reviewed,
                               current["inventory_sha256"])
        text = report(inventory, sections, rows, runs, ignored, args.source_url, audit_stats,
                      denominator_reviewed, measured)
        snapshot = {"schema": 1, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "inventory_sha256": current["inventory_sha256"],
                    "registry_sha256": hashlib.sha256((DATA / "behaviors.json").read_bytes()).hexdigest(),
                    "source_url": args.source_url,
                    "source_audit": audit_stats,
                    **stats, **measured, "execution": runs, "ignored_results": ignored}
        if args.json:
            executed_ids = set(runs["executed"])
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps({**snapshot,
                                             "requirements": [{"id": r["id"],
                                                               "clause": r["clause"],
                                                               "mapped": r["mapped"],
                                                               "executed": r["id"] in executed_ids,
                                                               "status": requirement_status(r, executed_ids)}
                                                              for r in rows]},
                                            ensure_ascii=False, indent=2) + "\n")
        if args.check:
            require(args.output.is_file() and args.output.read_text() == text,
                    f"stale report: run python3 tools/behavior_coverage.py --update")
        elif args.update or args.output != REPORT:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text)
            print(f"wrote {args.output}")
        else:
            print(text, end="")
        compact = summary_data(snapshot)
        summary_output = args.summary_output or (SUMMARY_REPORT if args.output == REPORT else None)
        summary_json = args.summary_json or (SUMMARY_JSON if args.output == REPORT else None)
        detail_link = os.path.relpath(args.output, summary_output.parent) if summary_output else args.output.name
        artifacts = [(summary_output, compact_report(compact, args.source_url, detail_link)),
                     (summary_json, json.dumps(compact, ensure_ascii=False, indent=2) + "\n")]
        for path, content in artifacts:
            if path is None:
                continue
            if args.check:
                require(path.is_file() and path.read_text() == content,
                        f"stale coverage summary: {path}; run --update")
            elif args.update or args.output != REPORT:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
        if args.require_complete:
            require(stats["whole_standard_percent"] == stats["whole_standard_executed_percent"] == 100,
                    "whole-standard denominator is incomplete or behaviors lack tests/fresh passes")
        if args.require_source_reviewed:
            require(audit_stats["source_review_complete"],
                    "some sections lack a complete source-block classification")
        if args.history:
            require(not args.check, "--check cannot append measurement history")
            append_history(args.history, summary_data(snapshot, keep_timestamp=True))
    except (InvalidCoverage, KeyError, TypeError, OSError, ValueError) as exc:
        print(f"behavior coverage: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
