#!/usr/bin/env python3
"""Inventory every existing test's reviewed links and unapproved clause candidates.

Candidates are a worklist, never behavioral coverage or completed content reviews.
"""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import behavior_coverage as coverage
import suite_results

OUTPUT = coverage.DATA / "test-matching.json"
REPORT = coverage.ROOT / "docs/test-requirement-matching.md"
DISPOSITIONS = "test-matching-reviews.json"
DISPOSITION_KINDS = {"partial_observation", "oracle_issue", "citation_refinement",
                     "compound_requirement"}


def attach_dispositions(data: dict, reviews: dict, rows: list[dict]) -> None:
    """Keep scoped review decisions separate from coverage approval and file completion."""
    coverage.require(reviews.get("schema") == 1 and isinstance(reviews.get("reviews"), list),
                     "invalid test review ledger")
    tests = {t["test"]: t for t in data["tests"]}
    ids = {r["id"] for r in rows}
    seen = set()
    counts = {kind: 0 for kind in sorted(DISPOSITION_KINDS)}
    for review in reviews["reviews"]:
        name = review.get("test")
        coverage.require(name in tests and name not in seen,
                         f"unknown or duplicate reviewed test: {name}")
        seen.add(name)
        coverage.require(review.get("inputs_sha256") == tests[name]["inputs_sha256"],
                         f"stale test review: {name}; review changed inputs")
        coverage.require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", review.get("reviewed_on", ""))
                         and review.get("reviewer") and review.get("scope"),
                         f"test review needs date, reviewer and scope: {name}")
        decisions = review.get("decisions")
        coverage.require(isinstance(decisions, list) and decisions,
                         f"test review needs scoped decisions: {name}")
        test = coverage.ROOT / name
        inputs = set(suite_results.input_files(test))
        for decision in decisions:
            kind = decision.get("disposition")
            selected = decision.get("requirement_ids")
            coverage.require(kind in DISPOSITION_KINDS and decision.get("explanation")
                             and isinstance(selected, list) and selected
                             and len(selected) == len(set(selected)) and set(selected) <= ids,
                             f"invalid scoped decision: {name}")
            anchors = decision.get("evidence", [])
            coverage.require(anchors and any(a["file"] == name for a in anchors),
                             f"test review needs stimulus evidence: {name}")
            for anchor in anchors:
                path = coverage.local_file(anchor["file"])
                coverage.require(path in inputs and anchor.get("contains")
                                 and anchor["contains"] in path.read_text(encoding="utf-8"),
                                 f"missing test review evidence: {name}")
            counts[kind] += 1
        tests[name]["scoped_review"] = review
    data["scoped_review_test_files"] = len(seen)
    data["review_disposition_counts"] = counts


def inventory(tests: list[Path], rows: list[dict]) -> dict:
    by_clause = defaultdict(list)
    linked = defaultdict(set)
    collective = defaultdict(set)
    descendant_counts = defaultdict(int)
    for row in rows:
        by_clause[row["clause"]].append(row)
        parts = row["clause"].split(".")
        for depth in range(1, len(parts)):
            descendant_counts[".".join(parts[:depth])] += 1
        for check in row["checks"]:
            linked[check["test"]].add(row["id"])
            if row.get("check_groups"):
                collective[check["test"]].add(row["id"])
    records = []
    for test in sorted(tests):
        name = test.relative_to(coverage.ROOT).as_posix()
        fields = suite_results.header(test)
        clauses = list(dict.fromkeys(fields.get("lrm", "").split()[1:]))
        negative = bool(fields.get("should_fail_because"))
        candidates, holds, other_kind = set(), set(), set()
        for clause in clauses:
            for row in by_clause[clause]:
                if row["id"] in linked[name]:
                    continue
                if row.get("interpretation_issue"):
                    holds.add(row["id"])
                elif (row["kind"] == "error") != negative:
                    other_kind.add(row["id"])
                else:
                    candidates.add(row["id"])
        records.append({"test": name, "inputs_sha256": suite_results.input_digest(test),
                        "cited_clauses": clauses, "negative_test": negative,
                        "registered_requirement_ids": sorted(linked[name]),
                        "collective_requirement_ids": sorted(collective[name]),
                        "unapproved_candidate_ids": sorted(candidates),
                        "interpretation_pending_ids": sorted(holds),
                        "different_case_kind_ids": sorted(other_kind),
                        "broader_citations": [{"clause": c,
                                               "descendant_requirement_count": descendant_counts[c]}
                                              for c in clauses if descendant_counts[c]]})
    chapters = []
    for chapter in sorted({Path(r["test"]).parent.name for r in records},
                          key=lambda c: int(c.removeprefix("ch"))):
        group = [r for r in records if Path(r["test"]).parent.name == chapter]
        count = sum(bool(r["registered_requirement_ids"]) for r in group)
        chapters.append({"chapter": chapter, "test_files": len(group),
                         "linked_test_files": count, "unlinked_test_files": len(group) - count})
    count = sum(bool(r["registered_requirement_ids"]) for r in records)
    return {"schema": 1, "standard": "IEEE 1800-2023",
            "note": "Candidate enumeration is complete for the current suite, not semantic review. "
                    "Only explicitly reviewed behaviors.json checks count as registered links. "
                    "A linked file is not a completed review of every observation in that file.",
            "test_files": len(records), "linked_test_files": count,
            "unlinked_test_files": len(records) - count, "chapters": chapters, "tests": records}


def report(data: dict) -> str:
    lines = ["# 既存テストと規格要求の照合", "",
             "[動作カバレッジ集計](behavior-coverage-summary.md) / "
             "[全テストの照合台帳](../coverage/test-matching.json) / "
             "[内容確認で見つかった問題](existing-test-matching-review-20261022.md)", "",
             f"全 {data['test_files']} 本を対象に、引用節から照合候補を列挙しました。",
             f"刺激・期待結果に基づく要求対応が登録済みのテストは {data['linked_test_files']} 本、"
             f"未登録は {data['unlinked_test_files']} 本です。", "",
             "**全テストの意味上の照合は未完了です。** 候補列挙は自動処理で、対応の承認ではありません。",
             "登録済み本数も、少なくとも一つの要求との対応がある本数で、各テスト全体の確認完了数ではありません。",
             "一つのテストの複数観測や、同じ要求を検証する別テストの対応も順次記録します。", "",
             "## 台帳の読み方", "",
             "- `registered_requirement_ids`: 刺激・期待結果を確認して対応を登録した要求。"
             "証拠とレビュー担当・日付は `behaviors.json` の `checks` にあります。",
             "- `collective_requirement_ids`: 複数テストで分担する要求への参加。"
             "そのテスト単独では要求全体を検証したことにならず、指定グループの全成功が必要です。",
             "- `unapproved_candidate_ids`: 引用節と正常／違法の区分が一致する候補。"
             "名前や引用だけから対応済みにしていません。",
             "- `interpretation_pending_ids`: 引用節の解釈保留項目。対応の承認対象から分けています。",
             "- `different_case_kind_ids`: 引用節は一致するが正常／違法の区分が異なる項目。"
             "要求行が複数条件を含む場合は、要求の分割が必要かも確認します。",
             "- `broader_citations`: 引用節の下位節にも要求がある箇所。"
             "直接候補がなくても、テストが無関係という判定にはなりません。",
             "- `inputs_sha256`: 照合候補を作成した入力の識別子。"
             "テスト・期待値・補助ファイルが変われば再照合します。", "",
             "候補のない要求や未登録のテストを、テストが存在しない証拠として扱わないでください。",
             "複合要求の一部しか観測しないテスト、必須の境界条件を欠くテスト、"
             "誤った期待値や違法な刺激を含むテストは、そのまま要求全体に対応付けません。", ""]
    if "scoped_review_test_files" in data:
        lines += ["## 対応を保留した理由", "",
                  f"{data['scoped_review_test_files']} 本について、確認した範囲と判断を "
                  "[レビュー判断台帳](../coverage/test-matching-reviews.json)に記録しました。",
                  "これは範囲を限定した判断の記録で、テスト全体のレビュー完了数ではありません。"
                  "対応登録や動作網羅率を増やす情報としては使用しません。",
                  "入力ハッシュ・根拠の文字列・要求IDを検査し、変更後の判断の使い回しを防ぎます。", ""]
        for kind, count in data["review_disposition_counts"].items():
            lines.append(f"- `{kind}`: {count} 件。")
        lines.append("")
    lines += ["## 章別の登録状況", ""]
    for c in data["chapters"]:
        lines.append(f"- {c['chapter']}: 全 {c['test_files']} 本、対応登録済み "
                     f"{c['linked_test_files']} 本、未登録 {c['unlinked_test_files']} 本。")
    lines += ["", "## 更新・検査", "", "```sh",
              "python3 tools/requirement_matching.py --update",
              "python3 tools/requirement_matching.py --check", "```", "",
              "`--check` は入力と対応の変更による台帳の古さを検出します。"
              "未登録項目が残ること自体では失敗しません。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--update", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        registry_path = coverage.DATA / "behaviors.json"
        source_path = coverage.DATA / "standard-sections.json"
        registry_bytes, source_bytes = registry_path.read_bytes(), source_path.read_bytes()
        review_path = coverage.DATA / DISPOSITIONS
        review_bytes = review_path.read_bytes()
        registry, source = json.loads(registry_bytes), json.loads(source_bytes)
        _, rows = coverage.validate(source, registry)
        data = inventory(suite_results.find_tests(), rows)
        attach_dispositions(data, json.loads(review_bytes), rows)
        coverage.require(registry_path.read_bytes() == registry_bytes
                         and source_path.read_bytes() == source_bytes
                         and review_path.read_bytes() == review_bytes,
                         "registry changed during matching; rerun")
        fingerprints = {r["test"]: r["inputs_sha256"] for r in data["tests"]}
        coverage.require(all(fingerprints.get(c["test"]) == c["inputs_sha256"]
                             for row in rows for c in row["checks"]),
                         "reviewed input changed during matching; review and rerun")
        reviewed = {c["test"] for row in rows for c in row["checks"]}
        reviewed.update(r["test"] for r in json.loads(review_bytes)["reviews"])
        coverage.require(all(suite_results.input_digest(coverage.ROOT / name) == fingerprints[name]
                             for name in reviewed),
                         "reviewed input changed during matching; review and rerun")
        data["registry_sha256"] = hashlib.sha256(registry_bytes).hexdigest()
        data["inventory_sha256"] = hashlib.sha256(source_bytes).hexdigest()
        data["review_ledger_sha256"] = hashlib.sha256(review_bytes).hexdigest()
        for path, text in [(OUTPUT, json.dumps(data, ensure_ascii=False, indent=2) + "\n"),
                           (REPORT, report(data))]:
            if args.check:
                coverage.require(path.is_file() and path.read_text() == text,
                                 f"stale test matching: {path}; run --update")
            else:
                path.write_text(text)
        print(f"{data['test_files']} tests inventoried; {data['linked_test_files']} have reviewed links; "
              "semantic review remains incomplete")
        return 0
    except (coverage.InvalidCoverage, OSError, ValueError, KeyError) as exc:
        print(f"test matching: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
