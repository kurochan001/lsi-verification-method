#!/usr/bin/env python3
"""Reconcile a portable verification plan with adapter-produced execution evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def names(value, label):
    if (not isinstance(value, list) or not value or
            any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]+', v) for v in value) or
            len(value) != len(set(value))):
        raise ValueError('invalid/duplicate ' + label)
    return value


def source_path(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('source path must be relative to --root')
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('missing/outside-root source: ' + name)
    return path


def index(rows, label):
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        raise ValueError('nonempty objects required: ' + label)
    ids = names([r.get('id') for r in rows], label)
    return dict(zip(ids, rows))


def audit(plan, evidence, root, plan_sha256, evidence_dir):
    """Trust the named adapter's semantics; verify mappings, counts and freshness."""
    errors, items = [], []
    try:
        if type(plan.get('schema_version')) is not int or type(evidence.get('schema_version')) is not int or plan['schema_version'] != 1 or evidence['schema_version'] != 1:
            raise ValueError('unsupported schema_version')
        names([plan.get('id')], 'plan id')
        if evidence.get('plan_id') != plan['id'] or evidence.get('plan_sha256') != plan_sha256:
            errors.append('STALE_PLAN: evidence does not identify this plan revision')
        sources = plan.get('sources')
        if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s for s in sources) or len(sources) != len(set(sources)):
            raise ValueError('invalid/duplicate source paths')
        hashes = evidence.get('source_sha256')
        if not isinstance(hashes, dict) or set(hashes) != set(sources):
            raise ValueError('SOURCE_INVENTORY: source snapshot differs from plan')
        for name in sources:
            if digest(source_path(root, name)) != hashes[name]:
                errors.append('STALE_SOURCE: ' + name)
        requirements = index(plan.get('requirements'), 'requirements')
        tests = index(plan.get('tests'), 'tests')
        points = index(plan.get('items'), 'items')
        for req in requirements.values():
            if req.get('source') not in sources or not isinstance(req.get('anchor'), str) or not req['anchor']:
                raise ValueError('SOURCE_REFERENCE: ' + req['id'])
            if req['anchor'] not in source_path(root, req['source']).read_text():
                errors.append('SOURCE_ANCHOR: ' + req['id'])
        for test in tests.values():
            names([test.get('configuration')], 'configuration')
        bound_requirements, bound_tests, known_checkers, known_goals = set(), set(), set(), set()
        for point in points.values():
            for key in ('requirements', 'tests', 'checkers', 'goals', 'configurations'):
                names(point.get(key), key)
            if set(point['requirements']) - requirements.keys() or set(point['tests']) - tests.keys():
                raise ValueError('UNKNOWN_REFERENCE: ' + point['id'])
            configurations = {tests[t]['configuration'] for t in point['tests']}
            if configurations != set(point['configurations']):
                raise ValueError('CONFIGURATION_PLAN: ' + point['id'])
            if type(point.get('min_hits', 1)) is not int or point.get('min_hits', 1) < 1:
                raise ValueError('invalid min_hits')
            bound_requirements.update(point['requirements']); bound_tests.update(point['tests'])
            known_checkers.update(point['checkers']); known_goals.update(point['goals'])
        if bound_requirements != requirements.keys():
            errors.append('UNMAPPED_REQUIREMENT: ' + ','.join(sorted(requirements.keys() - bound_requirements)))
        if bound_tests != tests.keys():
            errors.append('UNMAPPED_TEST: ' + ','.join(sorted(tests.keys() - bound_tests)))
        results = {} if evidence.get('results') == [] else index(evidence.get('results'), 'results')
        if results.keys() != tests.keys():
            errors.append('TEST_INVENTORY: missing or unplanned execution')
        artifacts = evidence.get('artifacts')
        if not isinstance(artifacts, dict) or not artifacts:
            raise ValueError('ARTIFACT_INVENTORY: no underlying execution artifacts')
        for name, expected in artifacts.items():
            path = Path(name)
            if not path.is_absolute(): path = evidence_dir / path
            if not path.is_file() or digest(path) != expected:
                errors.append('STALE_ARTIFACT: ' + name)
        for rid, result in results.items():
            if rid not in tests: continue
            if result.get('configuration') != tests[rid]['configuration']:
                errors.append('WRONG_CONFIGURATION: ' + rid)
            if result.get('status') != 'pass' or result.get('complete') is not True:
                errors.append('INCOMPLETE_OR_FAILED_TEST: ' + rid)
            if type(result.get('comparisons')) is not int or result['comparisons'] < 1:
                errors.append('ZERO_COMPARISONS: ' + rid)
            for key, inventory in [('checkers', known_checkers), ('goals', known_goals)]:
                counts = result.get(key)
                if (not isinstance(counts, dict) or set(counts) - inventory or
                        any(type(n) is not int or n < 0 for n in counts.values())):
                    raise ValueError('INVALID_COUNTERS: ' + rid + '/' + key)
        for point in points.values():
            missing = []
            for configuration in point['configurations']:
                valid = [results[t] for t in point['tests'] if t in results and
                         results[t].get('configuration') == configuration and results[t].get('status') == 'pass' and
                         results[t].get('complete') is True and type(results[t].get('comparisons')) is int and results[t]['comparisons'] > 0]
                # Goals from a different, unchecked execution cannot borrow this
                # item's checker completions from another passing test.
                valid = [r for r in valid if all(r['checkers'].get(c, 0) > 0 for c in point['checkers'])]
                for key in ('checkers', 'goals'):
                    for target in point[key]:
                        if sum(r[key].get(target, 0) for r in valid) < point.get('min_hits', 1):
                            missing.append(configuration + '/' + key + '/' + target)
            items.append(dict(id=point['id'], requirements=point['requirements'], success=not missing, missing=missing))
            if missing: errors.append('UNMET_ITEM: ' + point['id'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append('INVALID_EVIDENCE: ' + str(exc))
    if errors:
        for item in items:
            item['success'] = False
    return dict(success=not errors, errors=errors, items=items)


def write_report(out, report):
    out.mkdir(parents=True, exist_ok=False)
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    suite = ET.Element('testsuite', name='verification-plan', tests=str(len(report['items']) + 1),
                       failures=str(sum(not i['success'] for i in report['items']) + int(bool(report['errors']))), errors='0')
    gate = ET.SubElement(suite, 'testcase', name='evidence-integrity')
    if report['errors']: ET.SubElement(gate, 'failure', message='; '.join(report['errors']))
    for item in report['items']:
        case = ET.SubElement(suite, 'testcase', name=item['id'])
        if not item['success']: ET.SubElement(case, 'failure', message=', '.join(item['missing']))
    ET.indent(suite); ET.ElementTree(suite).write(out / 'junit.xml', encoding='utf-8', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd()); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists(): parser.error('output exists; choose a new --out')
    try:
        report = audit(json.loads(args.plan.read_text()), json.loads(args.evidence.read_text()),
                       args.root.resolve(), digest(args.plan), args.evidence.resolve().parent)
    except (OSError, ValueError) as exc: report = dict(success=False, errors=[str(exc)], items=[])
    write_report(args.out, report)
    print('Verification plan:', 'PASS' if report['success'] else 'FAIL')
    for error in report['errors']: print(error)
    return 0 if report['success'] else 1


if __name__ == '__main__': sys.exit(main())
