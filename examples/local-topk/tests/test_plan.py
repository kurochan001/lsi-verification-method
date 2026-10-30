from itertools import product
from pathlib import Path
import random, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-topk')
HERE = Path(__file__).resolve().parents[1]


def stable_topk(scores, k):
    """Independent reference: Python's stable sort by descending score."""
    order = sorted(range(len(scores)), key=lambda j: -scores[j])[:k]
    return [scores[j] for j in order], order


def simulate(n, k, mutation, vectors):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'v.txt').write_text(''.join(format(sum((s & 0xff) << (8 * j) for j, s in enumerate(v)), 'x') + '\n'
                                           for v in vectors))
        subprocess.run(['iverilog', '-g2012', '-s', 'topk_tb', '-o', str(tmp / 'sim.vvp'), f'-Ptopk_tb.N={n}',
                        f'-Ptopk_tb.K={k}', f'-Ptopk_tb.MUTATION={mutation}', str(HERE / 'rtl/topk_select.sv'),
                        str(HERE / 'tb/topk_tb.sv')], check=True, capture_output=True, timeout=60)
        out = subprocess.run(['vvp', str(tmp / 'sim.vvp'), f"+VECTORS={tmp / 'v.txt'}"], check=True,
                             capture_output=True, text=True, timeout=120).stdout
    width = (n - 1).bit_length()
    results = []
    for line in out.splitlines():
        if line.startswith('OUT '):
            scores, index = (int(field, 16) for field in line.split()[1:])
            results.append(([((scores >> (8 * i)) & 0xff) - 256 * ((scores >> (8 * i + 7)) & 1) for i in range(k)],
                            [(index >> (width * i)) & ((1 << width) - 1) for i in range(k)]))
    return results


class PlanTest(unittest.TestCase):
    def test_plan_has_a_proof_a_cover_and_four_counterexamples(self):
        plan = P.plan(P.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['topk-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 5)])
        self.assertEqual(plan[0]['depth'], P.PROOF_DEPTH)
        self.assertEqual({c['depth'] for c in plan[1:]}, {P.BOUND})
        self.assertEqual([c['failure'] for c in plan[2:]], ['ap_ties', 'ap_topk', 'ap_index', 'ap_topk'])

    def test_demo_fault_reaches_only_the_proof(self):
        plan = P.plan(P.BOUND, 3)
        self.assertEqual(plan[0]['parameters']['MUTATION'], 3)
        self.assertEqual(plan[1]['parameters']['MUTATION'], 0)

    def test_every_task_compiles_the_same_properties(self):
        for case in P.plan(P.BOUND, 0):
            props = P.properties(P.CONFIGS['n4-k2'], case)
            self.assertEqual(props['assert'], P.ASSERTS)
            self.assertEqual(props['cover'], P.COVERS)
            self.assertEqual(props['assume'], {'as_initial_reset'})

    def test_simulation_agrees_with_a_stable_sort_and_each_mutant_disagrees(self):
        if not (shutil.which('iverilog') and shutil.which('vvp')):
            self.skipTest('Icarus required')
        rng = random.Random(3)
        small = [list(v) for v in product((-128, -1, 0, 1, 127), repeat=4)]
        wide = [[rng.choice((-128, -2, -1, 0, 1, 2, 127)) for _ in range(8)] for _ in range(1500)]
        for (n, k), vectors in (((4, 2), small), ((8, 3), wide)):
            expected = [stable_topk(v, k) for v in vectors]
            with self.subTest(n=n, mutation=0):
                self.assertEqual(simulate(n, k, 0, vectors), expected)
            for mutation in range(1, 5):
                with self.subTest(n=n, mutation=mutation):
                    self.assertNotEqual(simulate(n, k, mutation, vectors), expected)


if __name__ == '__main__':
    unittest.main()
