#!/usr/bin/env python3
"""Find a testbench race: a clocked block assigns with `=`, and something else reads it on that edge.

The readers are a continuous assignment, a net declaration with an initial value, a port
connection (also through `.*`) and another block on the same edge. Which side runs first is then up
to the simulator, so the result can differ between simulators without anything being wrong in the
design. This is a text search, written for the style of this repository: finding nothing does not
prove that a testbench has no race.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
CLOCKED = re.compile(r'\balways(?:_ff)?\s*@\s*\(\s*((?:pos|neg)edge\s+\w+)[^)]*\)')
ASSIGNED = re.compile(r'(?:^|[;\s])([A-Za-z_]\w*)(?:\[[^\]]*\])?\s*=(?!=)')
KEYWORDS = {'if', 'else', 'for', 'begin', 'end', 'int', 'integer', 'automatic', 'bit', 'logic', 'reg', 'wire'}
IMPLICIT = re.compile(r'\b([A-Za-z_]\w*)\s*(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?[A-Za-z_]\w*\s*\(\s*\.\*\s*\)')


def strip_comments(text):
    return re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', text, flags=re.S))


def clocked_blocks(text):
    blocks = []
    for match in CLOCKED.finditer(text):
        tail = text[match.end():]
        if tail.lstrip().startswith('begin'):
            depth = 0
            end = len(tail)
            for token in re.finditer(r'\b(begin|end)\b', tail):
                depth += 1 if token.group(1) == 'begin' else -1
                if depth == 0:
                    end = token.end()
                    break
            body = tail[:end]
        else:
            body = tail[:tail.find(';') + 1]
        blocks.append((' '.join(match.group(1).split()), body))
    return blocks


def module_headers(paths):
    """Each module's header up to its `;`, which is where its port names are."""
    headers = {}
    for path in paths:
        text = strip_comments(path.read_text(errors='replace'))
        for match in re.finditer(r'\bmodule\s+(?:automatic\s+)?([A-Za-z_]\w*)([^;]*);', text):
            headers.setdefault(match.group(1), match.group(2))
    return headers


def find_races(text, headers=None):
    """Return (edge, signal, reason) for each race, in the order of the blocks."""
    text = strip_comments(text)
    blocks = clocked_blocks(text)
    implicit = [headers[name] for name in IMPLICIT.findall(text) if headers and name in headers]
    found = []
    for index, (edge, body) in enumerate(blocks):
        loopless = re.sub(r'\bfor\s*\([^)]*\)', 'for()', body)
        for name in sorted(set(ASSIGNED.findall(loopless)) - KEYWORDS):
            word = r'\b' + re.escape(name) + r'\b'
            reasons = []
            if re.search(r'\bassign\b[^;]*=[^;]*' + word, text):
                reasons.append('read by a continuous assignment')
            if re.search(r'\b(?:wire|logic)\b[^;]*=[^;]*' + word + r'[^;]*;', text):
                reasons.append('read by a net declaration')
            if re.search(r'\.\w+\s*\(\s*[^()]*' + word + r'[^()]*\)', text):
                reasons.append('in a port connection')
            if any(re.search(word, header) for header in implicit):
                reasons.append('in an implicit port connection')
            if any(other != index and blocks[other][0] == edge and re.search(word, blocks[other][1])
                   for other in range(len(blocks))):
                reasons.append('read by another block on the same edge')
            found += [(edge, name, reason) for reason in reasons]
    return found


def testbenches(root):
    examples = root / 'examples'
    return sorted(path for path in examples.rglob('*') if path.suffix in ('.sv', '.v') and 'upstream' not in path.parts
                  and ('tb' in path.parts or path.name.endswith('_tb.sv')))


def scan(root=ROOT):
    sources = sorted(path for path in (root / 'examples').rglob('*') if path.suffix in ('.sv', '.v'))
    headers = module_headers(sources)
    return [(path.relative_to(root).as_posix(), *race)
            for path in testbenches(root) for race in find_races(path.read_text(errors='replace'), headers)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    races = scan()
    for path, edge, name, reason in races:
        print(f'{path}: {name} is assigned with = at {edge} and {reason}')
    print(f'{len(testbenches(ROOT))} testbenches, {len(races)} possible races')
    return 1 if races else 0


if __name__ == '__main__':
    sys.exit(main())
