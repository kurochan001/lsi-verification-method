"""Exercise published Python validators without downloading upstream projects."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PICO = 'examples/reference-picorv32/README.md'
RANDOM = 'docs/method/random-search-management-walkthrough.md'
OPENTITAN = 'examples/reference-opentitan-dv/README.md'
MODES = [('normal', [], None), ('O', ['-O'], None),
         ('OO', ['-OO'], None), ('environment', [], '1')]


def cell(path, index=0):
    return re.findall(r"<<'PY'\n(.*?)\nPY", (ROOT / path).read_text(), re.S)[index]


def fake_git(pin):
    return f'''
import subprocess
def fixture_git(command, **kwargs):
    if command[-2:] == ['rev-parse', 'HEAD']:
        return {pin!r} + '\\n'
    if command[-2:] == ['status', '--porcelain']:
        return ''
    raise RuntimeError('unexpected Git query: ' + repr(command))
subprocess.check_output = fixture_git
'''


class DocumentedRecipesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_cell(self, code, base, mode, prelude='', toolbin=None):
        _, flags, optimize = mode
        env = dict(os.environ)
        env.pop('PYTHONOPTIMIZE', None)
        if optimize is not None:
            env['PYTHONOPTIMIZE'] = optimize
        if toolbin:
            env['PATH'] = str(toolbin) + os.pathsep + env.get('PATH', '')
        return subprocess.run([sys.executable, *flags, '-c', prelude + '\n' + code, str(base)],
                              cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=30)

    def executable(self, folder, name, text):
        folder.mkdir(exist_ok=True)
        p = folder / name
        p.write_text('#!/bin/sh\n' + text + '\n')
        p.chmod(0o755)

    def pico_fixture(self, base, compile_ok=False):
        repo = base / 'picorv32'
        repo.mkdir(parents=True)
        (repo / 'testbench_ez.v').write_text("$finish;\n32'h 00110113\nmem_ready <= 1;\n")
        for name in ['picorv32.v', 'Makefile', 'COPYING']:
            (repo / name).write_text('Fixture only\n')
        tools = base / 'bin'
        if compile_ok:
            self.executable(tools, 'iverilog', '''
write=0
for arg in "$@"; do
  if test "$write" = 1; then : > "$arg"; break; fi
  if test "$arg" = -o; then write=1; fi
done
exit 0''')
        else:
            self.executable(tools, 'iverilog', 'echo "injected compiler failure"\nexit 42')
        self.executable(tools, 'vvp', '''
case "$PWD" in
  */normal) echo 'PICOTOUR_PASS stores=8 loads=7'; exit 0;;
  */wrong-program) echo 'FATAL: PICOTOUR_DATA'; exit 1;;
  */no-response) echo 'FATAL: PICOTOUR_TIMEOUT'; exit 1;;
  *) echo 'Fixture simulator version'; exit 0;;
esac''')
        return tools

    def test_pico_compile_failure_cannot_report_success(self):
        for mode in MODES:
            with self.subTest(mode=mode[0]):
                base = self.root / mode[0]
                tools = self.pico_fixture(base)
                run = self.run_cell(cell(PICO), base, mode,
                                    fake_git('ef203c2b0a3fb793280f5114941416c425c5b461'), tools)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertIn('build failed', run.stdout)
                self.assertFalse((base / 'pico-summary.json').exists())

    def test_pico_expected_results_can_complete(self):
        # Tool fixtures test runner decisions; the real CPU is exercised manually.
        for mode in MODES:
            with self.subTest(mode=mode[0]):
                base = self.root / mode[0]
                tools = self.pico_fixture(base, compile_ok=True)
                run = self.run_cell(cell(PICO), base, mode,
                                    fake_git('ef203c2b0a3fb793280f5114941416c425c5b461'), tools)
                self.assertEqual(run.returncode, 0, run.stdout)
                summary = json.loads((base / 'pico-summary.json').read_text())
                self.assertTrue(summary['success'])
                self.assertEqual([(r['case'], r['returncode']) for r in summary['checked_cases']],
                                 [('normal', 0), ('wrong-program', 1), ('no-response', 1)])

    def test_unstable_input_generation_cannot_report_success(self):
        prelude = '''
import importlib.util
real_spec = importlib.util.spec_from_file_location
class UnstableLoader:
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        self.calls = 0
        def vectors(*args):
            self.calls += 1
            return [[0, 0, 0, self.calls]]
        module.random_vectors = vectors
def fixture_spec(name, location, *args, **kwargs):
    if name == 'fifo_duplicate_tour':
        return importlib.util.spec_from_loader(name, UnstableLoader())
    return real_spec(name, location, *args, **kwargs)
importlib.util.spec_from_file_location = fixture_spec
'''
        for mode in MODES:
            with self.subTest(mode=mode[0]):
                base = self.root / mode[0]
                base.mkdir()
                run = self.run_cell(cell(RANDOM), base, mode, prelude)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertIn('input uniqueness differs', run.stdout)
                self.assertFalse((base / 'input-summary.json').exists())

    def opentitan_fixture(self, base, duplicate=False, empty_install=False):
        base.mkdir()
        (base / 'plan.csv').write_text('name,ip\nreset,tutorial_top\nirq,tutorial_top\nbus_error,tutorial_ip\n')
        selected = [dict(name=n, bazel=['//example:' + n + '_test']) for n in ['reset', 'bus_error']]
        if duplicate:
            selected.append(dict(selected[0]))
        for name, data in [('selected', selected), ('field-before', [dict(stage='V2', si_stage='SV2')]),
                           ('field-after', [dict(si_stage='SV2')])]:
            (base / (name + '.hjson')).write_text(json.dumps(data))
        lock = 'version = 1\n'
        install = []
        digest = '0' * 64
        for name, version in [('click', '8.4.2'), ('hjson', '3.1.0'),
                              ('mako', '1.3.12'), ('markupsafe', '3.0.3')]:
            lock += f'\n[[package]]\nname="{name}"\nversion="{version}"\nwheels=[{{hash="sha256:{digest}"}}]\n'
            install.append(dict(metadata=dict(name=name, version=version),
                                download_info=dict(archive_info=dict(hashes=dict(sha256=digest)))))
        (base / 'opentitan/util/testplantool').mkdir(parents=True)
        (base / 'opentitan/uv.lock').write_text(lock)
        (base / 'opentitan/util/testplantool/cli.py').write_bytes(b'original CLI fixture')
        (base / 'testplantool-fixed').mkdir()
        (base / 'testplantool-fixed/cli.py').write_bytes(b'fixed CLI fixture')
        (base / 'python-install.json').write_text(json.dumps(dict(install=[] if empty_install else install)))
        return fake_git('0f8469f729ce8e84993c9987f90af3589172c79d') + '''
import hashlib, json, sys, types
# Parser fixtures isolate the validator and keep the tools tests usable on 3.10.
try:
    import tomllib
except ModuleNotFoundError:
    tomllib = types.ModuleType('tomllib')
    tomllib.loads = lambda text: {'package': []}
    sys.modules['tomllib'] = tomllib
hjson = types.ModuleType('hjson')
hjson.loads = json.loads
sys.modules['hjson'] = hjson
real_sha256 = hashlib.sha256
class FixtureDigest:
    def __init__(self, value):
        self.value = value
    def hexdigest(self):
        return self.value
def fixture_sha256(data):
    if data == b'original CLI fixture':
        return FixtureDigest('10f93df5d698778e86f529ca34ddad34f7dc56c37852b744d2c716136fee51d6')
    if data == b'fixed CLI fixture':
        return FixtureDigest('c25904043ed05275c458a52ddb1e471b7c5e6c1350f86490fb9794bdd0c07079')
    return real_sha256(data)
hashlib.sha256 = fixture_sha256
'''

    def test_opentitan_duplicate_query_records_are_rejected(self):
        for mode in MODES:
            with self.subTest(mode=mode[0]):
                base = self.root / mode[0]
                prelude = self.opentitan_fixture(base, duplicate=True)
                run = self.run_cell(cell(OPENTITAN, -1), base, mode, prelude)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertIn('query count or names differ', run.stdout)
                self.assertFalse((base / 'summary.json').exists())

    def test_opentitan_empty_dependency_inventory_is_rejected(self):
        for mode in MODES:
            with self.subTest(mode=mode[0]):
                base = self.root / mode[0]
                prelude = self.opentitan_fixture(base, empty_install=True)
                run = self.run_cell(cell(OPENTITAN, -1), base, mode, prelude)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertIn('installed package inventory differs', run.stdout)
                self.assertFalse((base / 'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
