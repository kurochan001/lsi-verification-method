"""Contract checks shared by local simulation examples."""
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
from local_test_support import assert_evidence,load_example,read_json,run_example

class SystemContract:
    def test_seed_reproduction(self):
        p=load_example(self.EXAMPLE);args=SimpleNamespace(profile='smoke',seed=17,iterations=2,demo_bug=0)
        parameters=next(iter(p.CONFIGS.values()));first=p.make_cases(args,parameters)
        self.assertEqual(first,p.make_cases(args,parameters))
        args.seed=18;self.assertNotEqual(first,p.make_cases(args,parameters))

    def test_real_rtl_all_configurations_and_mutants(self):
        if not (shutil.which('iverilog') and shutil.which('vvp')):self.skipTest('Icarus required')
        p=load_example(self.EXAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';result=run_example(self.EXAMPLE,out,'--iterations','3')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            assert_evidence(self,out,p.CONFIGS,self.GOALS,6*len(p.CONFIGS))

    def test_demo_faults_make_normal_regression_fail(self):
        if not (shutil.which('iverilog') and shutil.which('vvp')):self.skipTest('Icarus required')
        p=load_example(self.EXAMPLE);configuration=next(iter(p.CONFIGS))
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1,5):
                with self.subTest(fault=fault):
                    out=Path(tmp)/str(fault)
                    result=run_example(self.EXAMPLE,out,'--configuration',configuration,'--iterations','2','--demo-bug',str(fault))
                    self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                    self.assertEqual(read_json(out/f'{configuration}-boundaries/result.json')['status'],'fail')
