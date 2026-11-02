import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ngspice as N
import run_regression as R

class NgspiceTests(unittest.TestCase):
    def installation(self,root):
        home=root/'install';source=root/'source';source.mkdir();(source/'COPYING').write_text('fixture license')
        (source/'target.c').write_text('patched implementation')
        config=dict(release='47',repository='fixture',commit='0'*40,configure=[],patch=dict(target='target.c',patched_sha256=hashlib.sha256(b'patched implementation').hexdigest()))
        for name in ('include/ngspice/sharedspice.h','lib/'+N.library(home).name):
            path=home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
        return home,source,config

    def test_snapshot_detects_modified_missing_added_and_relabelled_files(self):
        for change in ('header','library','missing','extra','marker'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                home,source,config=self.installation(Path(tmp))
                with patch.object(N,'spec',return_value=config):
                    record=N.record_install(home,source);N.verify(record)
                    if change=='header':(home/'include/ngspice/sharedspice.h').write_text('changed')
                    elif change=='library':N.library(home).write_text('changed')
                    elif change=='missing':N.library(home).unlink()
                    elif change=='extra':(home/'lib/libngspice-extra').write_text('added')
                    else:
                        marker=json.loads((home/N.MARKER).read_text());marker['spec']['release']='48';(home/N.MARKER).write_text(json.dumps(marker))
                    with self.assertRaises(ValueError):N.verify(record)

    def test_unpatched_source_cannot_be_recorded_as_a_patched_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home,source,config=self.installation(Path(tmp));(source/'target.c').write_text('original implementation')
            with patch.object(N,'spec',return_value=config),self.assertRaisesRegex(ValueError,'patch is missing'):N.record_install(home,source)

    def test_configuration_wrapper_and_missing_campaign_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);home,source,config=self.installation(root)
            with patch.object(N,'spec',return_value=config):
                N.record_install(home,source)
                self.assertEqual(subprocess.check_output([str(home/'bin/lsi-ngspice-config'),'--version'],text=True).strip(),'ngspice 47')
            out=root/'result';out.mkdir();(root/'source.txt').write_text('fixture')
            (out/'manifest.json').write_text(json.dumps(dict(source_sha256={'source.txt':hashlib.sha256(b'fixture').hexdigest()})))
            (out/'summary.json').write_text(json.dumps(dict(success=True,planned=1,results=[dict(id='probe',status='pass')])))
            (out/'junit.xml').write_text('<testsuite tests="1"><testcase name="probe"/></testsuite>')
            with self.assertRaisesRegex(ValueError,'missing ngspice'):R.inspect_output(out,dict(tools=['lsi-ngspice-config']),{},root)
