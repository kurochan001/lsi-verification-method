import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import systemc as S
import build_native as N
import check_environment as E
import run_regression as R

class SystemcTests(unittest.TestCase):
    def installation(self,root):
        for name in ['include/systemc','include/systemc.h','lib/libsystemc.a',*[f'include/sysc/file{i}.h' for i in range(7)]]:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name)
        N.systemc_config(root,'2.3.4')

    def test_configuration_wrapper_reports_relocatable_prefix_and_exact_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.installation(root);command=str(root/'bin/lsi-systemc-config')
            for arg,want in [('--prefix',str(root.resolve())),('--version','SystemC 2.3.4')]:
                self.assertEqual(subprocess.check_output([command,arg],text=True).strip(),want)
            self.assertNotEqual(subprocess.run([command,'--unknown'],capture_output=True).returncode,0)
        self.assertTrue(E.version_ok('lsi-systemc-config','SystemC 2.3.4\n'))
        self.assertFalse(E.version_ok('lsi-systemc-config','SystemC 3.0.1\n'))

    def test_snapshot_rejects_changed_missing_or_added_header_and_library(self):
        for change in ('modify-header','modify-library','remove','add'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.installation(root);record=S.snapshot(root)
                self.assertEqual(S.verify(record),record)
                if change=='modify-header':(root/'include/sysc/file0.h').write_text('changed')
                elif change=='modify-library':(root/'lib/libsystemc.a').write_text('changed')
                elif change=='remove':(root/'include/systemc').unlink()
                else:(root/'include/sysc/new.h').write_text('added')
                with self.assertRaises(ValueError):S.verify(record)

    def test_systemc_example_requires_snapshot_even_if_summary_and_junit_pass(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';out.mkdir();source=root/'source';source.write_text('test')
            (out/'manifest.json').write_text(json.dumps(dict(source_sha256={'source':hashlib.sha256(source.read_bytes()).hexdigest()})))
            (out/'summary.json').write_text(json.dumps(dict(success=True,planned=1,results=[dict(id='test',status='pass')])))
            (out/'junit.xml').write_text('<testsuite tests="1"><testcase name="test"/></testsuite>')
            entry=dict(tools=['lsi-systemc-config'])
            with self.assertRaisesRegex(ValueError,'missing SystemC'):R.inspect_output(out,entry,{},root)
            prefix=root/'systemc';self.installation(prefix);record=S.snapshot(prefix)
            (out/'systemc-source.json').write_text(json.dumps(record))
            self.assertEqual(R.inspect_output(out,entry,{},root)['junit'],1)
            (prefix/'lib/libsystemc.a').write_text('changed')
            with self.assertRaisesRegex(ValueError,'SystemC'):R.inspect_output(out,entry,{},root)
