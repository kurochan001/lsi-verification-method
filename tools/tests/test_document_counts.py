"""Counts quoted in the documents must agree with what the repository holds now."""
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('kirimasim_examples', ROOT / 'tools/run_kirimasim_examples.py')
K = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(K)
REGISTRY = json.loads((ROOT / 'tools/regressions.json').read_text())


def rtl_files(root=ROOT):
    """Tracked or newly added .sv and .v files below an rtl directory of an example: the scope of the common lint."""
    listed = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', 'examples'],
                            cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
    return sorted(root / name for name in listed
                  if re.fullmatch(r'examples/(?:[^/]+/)+rtl/.+\.(sv|v)', name) and (root / name).is_file())


def timescale_counts(files):
    return len(files), sum('`timescale' in path.read_text(errors='replace') for path in files)


def quoted(text, pattern):
    return [tuple(map(int, match)) for match in re.findall(pattern, text)]


def root_jobs(registry):
    """Jobs of the entries that no aggregate or parent starts as a child."""
    entries = {entry['id']: entry for entry in registry['examples']}
    children = {child for entry in entries.values() for child in entry.get('children', {})}
    return sum(math.prod(len(values) for values in entry.get('matrix', {}).values())
               for name, entry in entries.items() if name not in children)


class DocumentCountTests(unittest.TestCase):
    def test_rtl_and_timescale_counts_in_the_readme_are_current(self):
        found = quoted((ROOT / 'README.md').read_text(), r'（(\d+)ファイル中(\d+)）')
        files = rtl_files()
        self.assertEqual(found, [timescale_counts(files)])
        inventory = json.loads((ROOT / 'tools/lint_targets.json').read_text())['rtl_files']
        self.assertEqual(sorted(str(path.relative_to(ROOT)) for path in files), sorted(inventory))

    def test_a_stale_count_is_noticed(self):
        files = rtl_files()
        total, with_timescale = timescale_counts(files)
        self.assertGreater(total, with_timescale)
        self.assertGreater(with_timescale, 0)
        self.assertNotEqual(timescale_counts(files[:-1])[0], total)
        self.assertEqual(quoted('RTLでは一部（109ファイル中27）にしか', r'（(\d+)ファイル中(\d+)）'), [(109, 27)])

    def test_kirimasim_selection_is_quoted_as_the_runner_lists_it(self):
        plan = K.selection_plan(REGISTRY)
        current = (plan['selected_examples'], plan['planned'])
        readme = (ROOT / 'README.md').read_text()
        self.assertEqual(quoted(readme, r'自動選択計画は(\d+)例・(\d+)構成'), [current])
        self.assertEqual(quoted((ROOT / 'tools/CI.md').read_text(), r'Icarus向け(\d+)例・(\d+)構成'), [current])
        study = (ROOT / 'docs/case-study-kirimasim/README.md').read_text()
        self.assertEqual(quoted(study, r'自動選択する計画は(\d+)例・(\d+)構成'), [current])

    def test_selection_plan_expands_the_matrices_of_pure_icarus_examples_only(self):
        registry = dict(examples=[
            dict(id='fifo', kind='simulation', tools=['iverilog', 'vvp'], matrix=dict(depth=[1, 3], width=[8, 16, 32])),
            dict(id='uart', kind='simulation', tools=['vvp', 'iverilog']),
            dict(id='gate', kind='simulation', tools=['iverilog', 'vvp', 'yowasp-yosys']),
            dict(id='proof', kind='formal', tools=['z3'])])
        self.assertEqual(K.selection_plan(registry), dict(examples=['fifo', 'uart'], selected_examples=2, planned=7))
        self.assertEqual(K.selection_plan(registry, ['uart'])['planned'], 1)

    def test_registry_size_and_root_jobs_are_current_wherever_they_are_quoted(self):
        current = (len(REGISTRY['examples']), root_jobs(REGISTRY))
        for name in ('examples/README.md', 'docs/method/open-source-dv-environments.md'):
            found = quoted((ROOT / name).read_text(), r'(\d+)登録項目・(\d+)ルートジョブ')
            self.assertTrue(found, name)
            self.assertEqual(set(found), {current}, name)

    def test_lint_scope_in_the_example_index_is_the_inventory(self):
        targets = json.loads((ROOT / 'tools/lint_targets.json').read_text())
        current = (len(targets['rtl_files']), len({(t['file'], t['top']) for t in targets['targets']}), len(targets['targets']))
        found = quoted((ROOT / 'examples/README.md').read_text(), r'共通lintの対象は(\d+) RTLファイル・(\d+)モジュール・(\d+)構成')
        self.assertEqual(found, [current])


if __name__ == '__main__':
    unittest.main()
