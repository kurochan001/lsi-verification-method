#!/usr/bin/env python3
"""Read complete, non-overlapping section bodies from the supplied standard.

The PDF/text stays outside this repository. --index writes only locations,
hashes and source-block identifiers, not the copyrighted source text. This
source inventory is an extraction-review checklist, not extracted requirements.
Use --show to read every block of a section, including examples and tables.
"""

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path

import behavior_coverage as coverage

DEFAULT_SOURCE = coverage.ROOT.parent / "sukimasim" / "IEEE_1800-2023_SystemVerilog"


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def source_sections(directory: Path, inventory: dict) -> dict:
    source = inventory["source"]
    pdf = directory / source["pdf"]
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != source["pdf_sha256"]:
        raise ValueError("the PDF differs from the inventoried edition")
    pages = (directory / "out/lrm_pdftotext_layout.txt").read_text().split("\f")
    lines, offsets = [], {}
    for page_number, page in enumerate(pages, 1):
        offsets[page_number] = len(lines)
        raw = page.splitlines()
        # All body pages have printed page = physical PDF page - 1. Keep
        # normative footnotes above it; remove running furniture below it.
        printed = [i for i, line in enumerate(raw)
                   if line.strip() == str(page_number - 1)]
        if printed and any("Copyright" in line for line in raw[printed[-1]:]):
            raw = raw[:printed[-1]]
        for number, line in enumerate(raw, 1):
            if (normalize(line) == "IEEE Std 1800-2023"
                    or (number <= 4 and normalize(line) == "1800-2023")
                    or normalize(line).startswith("IEEE Standard for SystemVerilog—Unified Hardware")
                    or "Authorized licensed use limited" in line):
                continue
            lines.append({"page": page_number, "line": number, "text": line})
    sections = sorted(inventory["sections"], key=lambda s: coverage.section_key(s["id"]))
    starts, missing = [], []
    for section in sections:
        number, page = section["id"], section["pdf_page"]
        title = normalize(section["title"])
        target = f"Annex {number}" if number.isalpha() else f"{number}{'.' if '.' not in number else ''} {title}"
        candidates = [(i, normalize(row["text"])) for i, row in enumerate(
            lines[offsets[page]:offsets[page + 1]], offsets[page])]
        exact = [i for i, text in candidates if text == target]
        if len(exact) != 1:
            missing.append({"id": number, "page": page, "title": title,
                            "matches": exact, "candidates": [text for _, text in candidates
                                                             if text.startswith(number + " ")]})
        else:
            starts.append((section, exact[0]))
    if missing:
        raise ValueError(json.dumps({"unresolved_headings": missing}, ensure_ascii=False, indent=2))
    positions = [position for _, position in starts]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise ValueError("section boundaries overlap or occur out of order")
    result = {}
    for index, (section, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else offsets[1354]
        body = lines[start:end]
        blocks, pending = [], []
        def flush():
            if pending:
                text = "\n".join(row["text"] for row in pending)
                digest = hashlib.sha256(text.encode()).hexdigest()
                blocks.append({"id": f"B{len(blocks)+1:03d}", "sha256": digest,
                               "start": [pending[0]["page"], pending[0]["line"]],
                               "end": [pending[-1]["page"], pending[-1]["line"]], "text": text})
                pending.clear()
        for row in body:
            if row["text"].strip():
                pending.append(row)
            else:
                flush()
        flush()
        # Heading is source evidence too, but not a standalone requirement.
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        result[section["id"]] = {"id": section["id"], "title": section["title"],
                                 "sha256": digest, "start": [body[0]["page"], body[0]["line"]],
                                 "end": [body[-1]["page"], body[-1]["line"]], "blocks": blocks}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--show", nargs="+", help="show complete own-body text for these sections")
    ap.add_argument("--index", type=Path, help="write source locations/hashes, without source text")
    ap.add_argument("--cache", type=Path, help="local-only full text cache; never commit it")
    args = ap.parse_args()
    inventory = json.loads((coverage.DATA / "standard-sections.json").read_text())
    sections = source_sections(args.source, inventory)
    if args.cache:
        if args.cache.resolve().is_relative_to(coverage.ROOT):
            ap.error("full standard text cache must stay outside the repository")
        args.cache.write_text(json.dumps(sections, ensure_ascii=False, indent=2) + "\n")
    if args.index:
        index = {"schema": 1, "pdf_sha256": inventory["source"]["pdf_sha256"],
                 "text_sha256": hashlib.sha256((args.source / "out/lrm_pdftotext_layout.txt").read_bytes()).hexdigest(),
                 "sections": {n: {**{k: v for k, v in s.items() if k != "blocks"},
                                   "blocks": [{k: v for k, v in b.items() if k != "text"}
                                              for b in s["blocks"]]}
                              for n, s in sections.items()}}
        args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    if args.show:
        for number in args.show:
            s = sections[number]
            print(f"\n### {number} {s['title']} {s['start']}–{s['end']}")
            for b in s["blocks"]:
                print(f"\n[{b['id']} PDF {b['start']}–{b['end']}]\n{b['text']}")
    if not args.show:
        print(f"{len(sections)} complete section bodies; "
              f"{sum(len(s['blocks']) for s in sections.values())} source blocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
