"""Prove on the real RTL what no clock pair in the simulation can show."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
INVARIANTS='  mailbox_invariants invariants(.src_up(src_up),.req(req),.present(present),.src_release(src_release),.req_sync(req_sync),.src_seen(src_seen));\n'


def sby(mode,depth,edit=None):
    """Return the tool output and the prepared model for one task."""
    tool=shutil.which('yowasp-sby')
    if not tool:raise unittest.SkipTest('yowasp-sby required')
    rtl=(HERE/'rtl/reset_mailbox.sv').read_text()
    if rtl.count('endmodule')!=1:raise ValueError('expected one module')
    if edit:
        if edit[0] not in rtl:raise ValueError(f'Edit target missing: {edit[0]}')
        rtl=rtl.replace(*edit)
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);(out/'rtl.sv').write_text(rtl.replace('endmodule',INVARIANTS+'endmodule'))
        (out/'task.sby').write_text(f'''[options]
mode {mode}
depth {depth}
multiclock on

[engines]
smtbmc z3

[script]
read -sv -formal rtl.sv mailbox_formal.sv
prep -flatten -top mailbox_formal

[files]
{out/'rtl.sv'}
{HERE/'formal/mailbox_formal.sv'}
''')
        result=subprocess.run([tool,'-f','task.sby'],cwd=out,capture_output=True,text=True,timeout=300)
        return result.stdout,(out/'task/model/design_prep.il').read_text()


class MailboxProofTests(unittest.TestCase):
    def test_the_src_seen_gate_cannot_change_dst_valid_on_any_clock_ratio(self):
        output,model=sby('prove',12)
        self.assertIn('successful proof by k-induction',output)
        self.assertIn('DONE (PASS',output)
        # Every assertion is present and none reads an unconnected signal.
        self.assertEqual(model.count('cell $assert'),7)
        self.assertNotIn('$anyseq',model)

    def test_the_proof_is_not_vacuous(self):
        output,_=sby('cover',40)
        self.assertIn('DONE (PASS',output)
        self.assertEqual(output.count('reached cover statement'),2)

    def test_the_proof_fails_when_the_chain_is_broken(self):
        output,_=sby('prove',12,("src_seen<={src_seen[0],src_up};","src_seen<={src_seen[0],1'b0};"))
        self.assertIn('DONE (FAIL',output)
        self.assertIn('failed assertion',output)


if __name__=='__main__':unittest.main()
