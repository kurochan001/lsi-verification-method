"""Check the extra evidence required of each two-configuration simulation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-domain-expansion')


class DomainAggregateTests(unittest.TestCase):
    def test_all_twelve_children_are_registered(self):
        entries = json.loads(P.REGISTRY.read_text())['examples']
        parent = next(entry for entry in entries if entry['id'] == P.NAME)
        self.assertEqual(len(parent['children']), 12)
        for name, directory in parent['children'].items():
            self.assertEqual(directory, name)
            self.assertTrue((P.HERE.parent / name / 'run.py').is_file())

    def test_child_identity_counts_and_coverage(self):
        entry = {'id': 'local-demo'}
        args = SimpleNamespace(profile='smoke', seed=17)
        manifest = dict(example=entry['id'], seed=17, configurations=dict(a={}, b={}))
        summary = dict(planned=12, functional_pass=4, mutations_detected=8)
        covered = dict(success=True, required=3, hit=3, missing=[])
        coverage = dict(a=covered, b=covered)
        with tempfile.TemporaryDirectory() as tmp, patch.object(P.R, 'inspect_output', return_value={'junit': 14}):
            out = Path(tmp)
            def verify(m, s, c):
                for key, value in [('manifest', m), ('summary', s), ('coverage', c)]:
                    (out / (key + '.json')).write_text(json.dumps(value))
                return P.verify_child(out, entry, {}, args)
            self.assertEqual(verify(manifest, summary, coverage), {'junit': 14})
            for m, s, c in [
                    (dict(manifest, seed=18), summary, coverage),
                    (dict(manifest, example='wrong-example'), summary, coverage),
                    (manifest, dict(summary, mutations_detected=7), coverage),
                    (manifest, summary, {'a': covered}),
                    (manifest, summary, dict(coverage, b=dict(covered, hit=2)))]:
                with self.subTest(m=m, s=s, c=c), self.assertRaises(ValueError):
                    verify(m, s, c)


if __name__ == '__main__':
    unittest.main()
