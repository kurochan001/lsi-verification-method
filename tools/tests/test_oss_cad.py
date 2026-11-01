import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import oss_cad as O

class ToolchainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.home=self.root/'oss-cad-suite';self.home.mkdir();self.binary=self.home/'tool';self.binary.write_text('official');self.binary.chmod(0o755)
        config=self.root/'pin.json';config.write_text(json.dumps(dict(schema_version=1,release='test',platforms={'fixture':dict(sha256='a'*64,tree_sha256=O.tree_digest(O.inventory(self.home)))})))
        self.patch=patch.object(O,'CONFIG',config);self.patch.start();self.addCleanup(self.patch.stop)
    def test_exact_identity_and_streaming_digest(self):
        self.assertEqual(O.verify(self.home,'fixture')['files'],1)
        self.assertEqual(O.digest(self.binary),hashlib.sha256(b'official').hexdigest())
    def test_modified_missing_and_added_files_fail(self):
        for action in ('modify','remove','add'):
            with self.subTest(action=action):
                self.binary.write_text('official');extra=self.home/'extra';extra.unlink(missing_ok=True)
                if action=='modify':self.binary.write_text('changed')
                elif action=='remove':self.binary.unlink()
                else:extra.write_text('added')
                with self.assertRaises(ValueError):O.verify(self.home,'fixture')
    def test_executable_permissions_are_bound(self):
        self.binary.chmod(0o644)
        with self.assertRaises(ValueError):O.verify(self.home,'fixture')
        with self.assertRaises(ValueError):O.bin_path(self.home,'tool')
    def test_symlink_target_and_escape_are_checked(self):
        link=self.home/'link';link.symlink_to('tool');before=O.tree_digest(O.inventory(self.home));link.unlink();link.symlink_to('./tool')
        self.assertNotEqual(before,O.tree_digest(O.inventory(self.home)))
        link.unlink();link.symlink_to('../outside')
        with self.assertRaises(ValueError):O.inventory(self.home)
    def test_unsupported_platform_is_not_substituted(self):
        with self.assertRaises(ValueError):O.config('unknown-cpu')
    def test_archive_escape_and_symlink_escape_fail(self):
        for name,target in [('../outside',None),('oss-cad-suite/../../outside',None),('oss-cad-suite/link','../../outside')]:
            with self.subTest(name=name):
                archive=self.root/'input.tgz'
                with tarfile.open(archive,'w:gz') as tar:
                    entry=tarfile.TarInfo(name)
                    if target:entry.type=tarfile.SYMTYPE;entry.linkname=target;tar.addfile(entry)
                    else:entry.size=1;tar.addfile(entry,io.BytesIO(b'x'))
                with self.assertRaises((ValueError,tarfile.TarError)):O.extract(archive,self.root/'unpack')
                self.assertFalse((self.root/'outside').exists())
    def test_bundled_python_cannot_rewrite_pinned_cache(self):
        with patch.dict(os.environ,{},clear=True):
            O.prepare_environment();self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'],'1')
if __name__=='__main__':unittest.main()
