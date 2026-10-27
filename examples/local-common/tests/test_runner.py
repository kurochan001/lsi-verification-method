import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_test_support import EXAMPLES,read_json,run_example


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.out=self.directory/'out'

    def run_cli(self,*options):
        return run_example('local-timer-watchdog',self.out,'--configuration','width4','--iterations','2',*options)

    def wrapper(self,body):
        path=self.directory/'fake-tool'
        path.write_text('#!'+sys.executable+'\nimport sys,subprocess,re,time\n'
                        'if "-V" in sys.argv: print("test tool");sys.exit(0)\n'+body+'\n')
        path.chmod(0o755)
        return str(path)

    def filter_vvp(self,expression):
        return self.wrapper(f'p=subprocess.run([{shutil.which("vvp")!r},*sys.argv[1:]],capture_output=True,text=True)\n'
                            f'output=p.stdout+p.stderr\nprint({expression},end="")\nsys.exit(p.returncode)')

    def assert_rejected(self,process):
        self.assertEqual(process.returncode,1,process.stdout+process.stderr)
        self.assertFalse(read_json(self.out/'summary.json')['success'])
        self.assertTrue((self.out/'junit.xml').exists())

    def test_missing_compiler(self):
        self.assert_rejected(self.run_cli('--iverilog',str(self.directory/'absent')))
        self.assertTrue(all(read_json(p)['status']=='error' for p in self.out.glob('*/result.json')))

    def test_compiler_nonzero(self):
        self.assert_rejected(self.run_cli('--iverilog',self.wrapper('print("compiler failed");sys.exit(3)')))

    def test_simulator_timeout(self):
        self.assert_rejected(self.run_cli('--timeout','0.2','--vvp',self.wrapper('time.sleep(3)')))
        self.assertTrue(any('timeout' in read_json(p)['message'] for p in self.out.glob('*/result.json')))

    def test_unrelated_crash_is_not_mutation_detection(self):
        self.assert_rejected(self.run_cli('--vvp',self.wrapper('print("unrelated crash");sys.exit(2)')))
        self.assertEqual(read_json(self.out/'summary.json')['mutations_detected'],0)

    def test_zero_exit_without_completion(self):
        self.assert_rejected(self.run_cli('--vvp',self.wrapper('sys.exit(0)')))

    def test_wrong_failure_label(self):
        self.assert_rejected(self.run_cli('--vvp',self.wrapper('print("CHECK_FAIL UNRELATED");sys.exit(1)')))
        self.assertEqual(read_json(self.out/'summary.json')['mutations_detected'],0)

    def test_missing_counts(self):
        self.assert_rejected(self.run_cli('--vvp',self.filter_vvp('re.sub(r"^COUNT .*\\n", "", output, flags=re.M)')))
        self.assertEqual(read_json(self.out/'summary.json')['functional_pass'],0)

    def test_incorrect_counts(self):
        self.assert_rejected(self.run_cli('--vvp',self.filter_vvp('re.sub(r"(?m)^COUNT timer_expiries=\\d+$", "COUNT timer_expiries=999999", output)')))

    def test_duplicate_counts(self):
        self.assert_rejected(self.run_cli('--vvp',self.filter_vvp('output+"COUNT timer_expiries=1\\n"')))

    def test_missing_normal_coverage_is_not_filled_by_mutations(self):
        expression='re.sub(r"^COVER .*\\n", "", output, flags=re.M) if sys.argv[1].endswith("-m0.vvp") else output'
        self.assert_rejected(self.run_cli('--vvp',self.filter_vvp(expression)))
        self.assertEqual(read_json(self.out/'summary.json')['mutations_detected'],4)
        self.assertEqual(read_json(self.out/'coverage.json')['width4']['hit'],0)

    def test_extra_required_goal_must_be_reached(self):
        catalog=read_json(EXAMPLES/'local-timer-watchdog/requirements.json')
        catalog['requirements'][0]['goals'].append('unreachable/goal')
        path=self.directory/'requirements.json';path.write_text(json.dumps(catalog))
        self.assert_rejected(self.run_cli('--requirements',str(path)))
        self.assertEqual(read_json(self.out/'coverage.json')['width4']['missing'],['unreachable/goal'])

    def test_duplicate_catalog_rejected_before_execution(self):
        catalog=read_json(EXAMPLES/'local-timer-watchdog/requirements.json')
        catalog['requirements'].append(catalog['requirements'][0])
        path=self.directory/'requirements.json';path.write_text(json.dumps(catalog))
        process=self.run_cli('--requirements',str(path))
        self.assertEqual(process.returncode,1)
        self.assertFalse(self.out.exists())

    def test_existing_output_preserved(self):
        self.out.mkdir();(self.out/'sentinel').write_text('keep')
        process=self.run_cli()
        self.assertEqual(process.returncode,2)
        self.assertEqual(list(self.out.iterdir()),[self.out/'sentinel'])
        self.assertEqual((self.out/'sentinel').read_text(),'keep')

    def test_demo_mutations_make_normal_regression_fail(self):
        for mutation in range(1,5):
            with self.subTest(mutation=mutation):
                self.out=self.directory/f'demo{mutation}'
                self.assert_rejected(self.run_cli('--demo-bug',str(mutation)))
                self.assertEqual(read_json(self.out/'width4-boundaries/result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
