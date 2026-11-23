"""Prove the fenced litmus outcome impossible and the relaxed one reachable."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
HERE = Path(__file__).resolve().parents[1]


def sby(top, mode, depth, edit=None):
    """Return the tool output and the prepared model for one task."""
    tool = shutil.which('yowasp-sby')
    yosys = shutil.which('yowasp-yosys')
    smtbmc = shutil.which('yowasp-yosys-smtbmc')
    if not (tool and yosys and smtbmc):
        raise unittest.SkipTest('yowasp-sby toolchain required')
    # sby looks for unprefixed yosys/yosys-smtbmc on PATH; CI provides only the yowasp wrappers.
    env = dict(os.environ, YOSYS=yosys, SMTBMC=smtbmc)
    witness = shutil.which('yowasp-yosys-witness')
    if witness:
        env['WITNESS'] = witness
    sources = {'rtl.sv': (HERE / 'rtl/litmus.sv').read_text(),
               'litmus_formal.sv': (HERE / 'formal/litmus_formal.sv').read_text()}
    if edit:
        name, old, new = edit
        if old not in sources[name]:
            raise ValueError(f'Edit target missing in {name}')
        sources[name] = sources[name].replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for name, text in sources.items():
            (out / name).write_text(text)
        (out / 'task.sby').write_text(f'''[options]
mode {mode}
depth {depth}

[engines]
smtbmc z3

[script]
read -sv -formal rtl.sv litmus_formal.sv
prep -flatten -top {top}

[files]
{out/'rtl.sv'}
{out/'litmus_formal.sv'}
''')
        result = subprocess.run([tool, '-f', 'task.sby'], cwd=out, capture_output=True, text=True,
                                timeout=300, env=env)
        model = out / 'task/model/design_prep.il'
        if not model.is_file():
            raise AssertionError(f'sby task produced no model ({result.returncode}):\n{result.stdout}\n{result.stderr}')
        return result.stdout, model.read_text()


class LitmusProofTests(unittest.TestCase):
    def test_the_fenced_litmus_outcome_is_impossible(self):
        output, model = sby('litmus_formal', 'prove', 12)
        self.assertIn('DONE (PASS', output)
        # Three helper assertions and the ordering requirement survive synthesis.
        self.assertEqual(model.count('cell $assert'), 4)

    def test_fenced_loads_can_finish(self):
        output, _ = sby('litmus_formal', 'cover', 12)
        self.assertIn('DONE (PASS', output)
        self.assertIn('reached cover statement', output)

    def test_the_relaxed_litmus_outcome_is_reachable(self):
        output, _ = sby('litmus_formal_relaxed', 'cover', 12)
        self.assertIn('DONE (PASS', output)
        self.assertEqual(output.count('reached cover statement'), 2)

    def test_the_fence_bypass_breaks_the_proof(self):
        output, _ = sby('litmus_formal', 'prove', 12,
                        ('litmus_formal.sv', '.FENCED(1), .MUTATION(0)',
                         '.FENCED(1), .MUTATION(1)'))
        self.assertIn('DONE (FAIL', output)
        self.assertIn('failed assertion', output)


if __name__ == '__main__':
    unittest.main()
