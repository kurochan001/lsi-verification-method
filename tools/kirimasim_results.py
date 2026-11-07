#!/usr/bin/env python3
"""Render a kirimasim campaign summary as Markdown tables.

The same output is the GitHub summary of each run and the recorded table in
docs/case-study-kirimasim/results.md. Anything short of a complete, passing
campaign is shown as a failure.
"""
import argparse
import json
from pathlib import Path
import re
import sys

COMMIT_URL = "https://github.com/kurochan001/kirimasim/commit/"
MESSAGE_LIMIT = 300


def cell(text):
    """Keep free-form text inside one table cell."""
    flat = " ".join(str(text).split())
    if len(flat) > MESSAGE_LIMIT:
        flat = flat[:MESSAGE_LIMIT - 1] + "…"
    return flat.replace("&", "&amp;").replace("<", "&lt;").replace("|", "\\|")


def exit_counts(codes):
    return "、".join(f"{code}が{count:,}回" for code, count in sorted(codes.items())) or "なし"


def overview(summary, commit, rows):
    passed, planned = summary["passed"], summary["planned"]
    verdict = "PASS" if summary["success"] and summary["complete"] else "FAIL"
    native = summary["native"]
    changes = summary["source_changes"]
    lines = ["| 項目 | 値 |", "| --- | --- |",
             f"| kirimasim | [`{commit[:12]}`]({COMMIT_URL}{commit}) |",
             f"| 計画 | {cell(summary['profile'])}、seed {summary['seed']}、"
             f"{summary['selected_examples']}例・{planned}構成 |",
             f"| 結果 | **{passed}／{planned} {verdict}** |"]
    if not summary["complete"]:
        lines.append(f"| 完了 | **未完了**（結果は{len(rows)}件） |")
    lines += [f"| lowering | {native['lowering']:,}回 |",
              f"| シミュレーション | {native['simulations']:,}回"
              f"（終了コード{exit_counts(summary['simulation_returncodes'])}） |",
              f"| 異常終了 | {native['abnormal']:,}回 |",
              "| 実行中の入力変更 | " + (cell("、".join(changes)) if changes else "なし") + " |"]
    return lines


def failures(rows):
    failed = [row for row in rows if not row["success"]]
    if not failed:
        return []
    lines = ["", "### 不合格の構成", "", "| 構成 | 内容 |", "| --- | --- |"]
    for row in failed:
        abnormal = row["native"]["abnormal"]
        detail = row.get("message", "") + (f"（異常終了{abnormal}回）" if abnormal else "")
        lines.append(f"| `{cell(row['id'])}` | {cell(detail)} |")
    return lines


def by_example(rows, examples_base):
    groups = {}
    for row in rows:
        groups.setdefault(row.get("example") or row["id"], []).append(row)
    lines = ["", "### 例ごとの結果", "",
             "| 例 | 構成 | 結果 | lowering | シミュレーション | 異常終了 |",
             "| --- | ---: | --- | ---: | ---: | ---: |"]
    for name, group in sorted(groups.items()):
        passed = sum(row["success"] for row in group)
        result = "PASS" if passed == len(group) else f"**FAIL**（{passed}／{len(group)}）"
        totals = [sum(row["native"][key] for row in group)
                  for key in ("lowering", "simulations", "abnormal")]
        lines.append(f"| [{cell(name)}]({examples_base}/{name}/README.md) | {len(group)} | {result} | "
                     + " | ".join(f"{value:,}" for value in totals) + " |")
    totals = [sum(row["native"][key] for row in rows)
              for key in ("lowering", "simulations", "abnormal")]
    lines.append(f"| 合計 | {len(rows)} | {sum(row['success'] for row in rows)}／{len(rows)} | "
                 + " | ".join(f"{value:,}" for value in totals) + " |")
    return lines


def render(summary, commit, examples_base):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"not a full kirimasim commit: {commit!r}")
    rows = summary["results"]
    return "\n".join(overview(summary, commit, rows) + failures(rows)
                     + by_example(rows, examples_base.rstrip("/"))) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="full kirimasim commit that was run")
    parser.add_argument("--examples-base", default="../../examples",
                        help="link prefix of the example directories")
    parser.add_argument("--out", type=Path, help="write here instead of standard output")
    args = parser.parse_args()
    try:
        text = render(json.loads(args.summary.read_text()), args.commit, args.examples_base)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"KIRIMASIM_RESULTS_ERROR {error!r}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
