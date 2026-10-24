#!/usr/bin/env python3
"""Validate source-block dispositions for completed requirement extraction.

Every source block must be accounted for. Hash/line inventories contain no
standard body text. A keyword scan, a section title or a cross-reference alone
cannot close an extraction review. Decisions explicitly name requirements or
explain why a block is non-normative/introductory notation.
"""

import hashlib
import json
from pathlib import Path

from behavior_coverage import require

DISPOSITIONS = {"heading", "requirements", "informative", "example", "reference"}


def validate(source_index: dict, audit: dict, sections: dict, requirements: list) -> dict:
    require(source_index.get("schema") == audit.get("schema") == 1, "unknown source audit schema")
    require(source_index["pdf_sha256"] == audit["pdf_sha256"], "audit PDF identity differs")
    require(source_index.get("text_sha256") and source_index["text_sha256"] == audit.get("text_sha256"),
            "audit text extraction identity differs")
    require(set(source_index["sections"]) == set(sections), "source audit inventory is incomplete")
    by_id = {r["id"]: r for r in requirements}
    for number, review in audit["sections"].items():
        require(number in sections, f"audit of unknown section {number}")
        source = source_index["sections"][number]
        require(review.get("state") in ("complete", "in_progress"), f"unknown audit state {number}")
        require(review.get("source_sha256") == source["sha256"], f"stale section audit {number}")
        require(review.get("reviewer") and review.get("reviewed_on") and review.get("scope_note")
                and review.get("visual_review"),
                f"audit needs author/date/scope note {number}")
        blocks = {b["id"] for b in source["blocks"]}
        require(set(review["blocks"]) == blocks, f"unaccounted or unknown source blocks {number}")
        requirement_ids = set()
        for bid, decision in review["blocks"].items():
            require(decision.get("disposition") in DISPOSITIONS and decision.get("rationale"),
                    f"unresolved source block {number}/{bid}")
            if decision["disposition"] == "requirements":
                require(decision.get("requirements"), f"block has no extracted rules {number}/{bid}")
                for rid in decision["requirements"]:
                    require(rid in by_id, f"unknown extracted rule {rid} at {number}/{bid}")
                    rule = by_id[rid]
                    spans = rule.get("source_spans", [])
                    require(any(s["section"] == number and bid in s["blocks"] for s in spans),
                            f"rule source does not acknowledge {number}/{bid}: {rid}")
                    requirement_ids.add(rid)
            if decision["disposition"] == "reference":
                require(decision.get("sections") and all(n in sections for n in decision["sections"]),
                        f"unresolved reference targets {number}/{bid}")
        state = sections[number]["review"]
        require(state in ("complete", "no_behavior") if review["state"] == "complete"
                else state == "in_progress", f"audit/section state differs {number}")
        if state == "no_behavior":
            require(not requirement_ids, f"no_behavior section has extracted obligations {number}")
        if state == "complete":
            require(bool(requirement_ids), f"completed audit has no obligations {number}")
    for number, section in sections.items():
        if section["review"] in ("complete", "no_behavior"):
            require(number in audit["sections"], f"completed section lacks source-block audit {number}")
    for rid, rule in by_id.items():
        if rule.get("interpretation_issue"):
            require(sections[rule["clause"]]["review"] == "in_progress",
                    f"unresolved interpretation cannot close its section: {rid}")
            require(not rule.get("checks"),
                    f"unresolved interpretation cannot have approved test mappings: {rid}")
        for span in rule.get("source_spans", []):
            require(span["section"] in audit["sections"], f"unreviewed source span for {rid}")
            decisions = audit["sections"][span["section"]]["blocks"]
            require(all(b in decisions and rid in decisions[b].get("requirements", [])
                        for b in span["blocks"]), f"orphaned rule/source association {rid}")
    return {"audited": len(audit["sections"]),
            "classified_blocks": sum(len(r["blocks"]) for r in audit["sections"].values())}


def load_and_validate(directory: Path, inventory: dict, registry: dict) -> dict:
    sections = {s["id"]: s for s in inventory["sections"]}
    source = json.loads((directory / "requirement-source-index.json").read_text())
    audit = json.loads((directory / "requirement-audit.json").read_text())
    require(source["pdf_sha256"] == inventory["source"]["pdf_sha256"], "source audit edition differs")
    stats = validate(source, audit, sections, registry["requirements"])
    stats.update(progress(source, audit, sections, registry["requirements"]))
    stats["source_index_sha256"] = hashlib.sha256(json.dumps(
        source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return stats


def progress(source: dict, audit: dict, sections: dict, requirements: list) -> dict:
    """Count fully classified source independently of interpretation approval.

    Call only after validate: an audit entry alone is insufficient evidence that
    every source block was classified. Open interpretations remain open, even
    when their source has been read and the disputed wording extracted.
    """
    reviewed = set(audit["sections"])
    normative = {n for n, s in sections.items() if s["kind"] == "normative"}
    issues = [r for r in requirements if r.get("interpretation_issue")]
    return {
        "sections_total": len(sections),
        "blocks_total": sum(len(s["blocks"]) for s in source["sections"].values()),
        "source_review_complete": reviewed == set(sections),
        "source_review_percent": 100 * len(reviewed) / len(sections) if sections else None,
        "normative_reviewed": len(reviewed & normative),
        "normative_source_review_percent": (100 * len(reviewed & normative) / len(normative)
                                            if normative else None),
        "interpretation_issues": len({r["interpretation_issue"].split(":", 1)[0]
                                      for r in issues}),
        "interpretation_issue_rows": len(issues),
        "interpretation_sections": sorted({r["clause"] for r in issues}),
    }
