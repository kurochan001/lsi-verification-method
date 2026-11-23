"""Prove the pipeline equals the delayed product for every input sequence."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
HERE = Path(__file__).resolve().parents[1]


def sby(mode, depth, edit=None):
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
    rtl = (HERE / 'rtl/mul_pipe.sv').read_text()
    if edit:
        if edit[0] not in rtl:
            raise ValueError(f'Edit target missing: {edit[0]}')
        rtl = rtl.replace(*edit)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / 'rtl.sv').write_text(rtl)
        (out / 'task.sby').write_text(f'''[options]
mode {mode}
depth {depth}

[engines]
smtbmc z3

[script]
read -sv -formal rtl.sv mul_pipe_formal.sv
prep -flatten -top mul_pipe_formal

[files]
{out/'rtl.sv'}
{HERE/'formal/mul_pipe_formal.sv'}
''')
        result = subprocess.run([tool, '-f', 'task.sby'], cwd=out, capture_output=True, text=True,
                                timeout=300, env=env)
        model = out / 'task/model/design_prep.il'
        if not model.is_file():
            raise AssertionError(f'sby task produced no model ({result.returncode}):\n{result.stdout}\n{result.stderr}')
        return result.stdout, model.read_text()


class MultiplierProofTests(unittest.TestCase):
    def test_the_pipeline_equals_the_delayed_product_for_any_trace(self):
        output, model = sby('prove', 10)
        self.assertIn('DONE (PASS', output)
        # One assertion cell: ap_product. A vacuous harness would have zero live cells.
        self.assertEqual(model.count('cell $assert'), 1)

    def test_the_proof_is_not_vacuous(self):
        output, _ = sby('cover', 40)
        self.assertIn('DONE (PASS', output)
        self.assertEqual(output.count('reached cover statement'), 2)

    def test_the_proof_fails_when_a_partial_product_is_misaligned(self):
        output, _ = sby('prove', 10, ("MUTATION == 1 ? {4'b0, hi} : {hi, 4'b0}", "{4'b0, hi}"))
        self.assertIn('DONE (FAIL', output)
        self.assertIn('failed assertion', output)


if __name__ == '__main__':
    unittest.main()
