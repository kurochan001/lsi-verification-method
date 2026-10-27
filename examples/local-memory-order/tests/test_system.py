from pathlib import Path
import sys
import shutil,subprocess,tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-memory-order')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-memory-order';GOALS=9

    def test_original_plan_excludes_collision_but_new_plan_includes_it(self):
        req=P.BASE.request
        with self.assertRaises(ValueError):P.BASE.Plan().batch(req(1,0),req(2,0))
        row=P.batch(req(1,0),req(2,0));self.assertEqual((row[1],row[15]),(0,0))
    def test_oracle_corruption_is_separate_from_rtl_mutations(self):
        from types import SimpleNamespace
        cases=P.make_cases(SimpleNamespace(seed=17,iterations=1,profile='smoke',demo_bug=0),{})
        case=next(c for c in cases if c['mutation']==3)
        self.assertEqual(case['expected_failure'],'ORDER_READ')
        self.assertTrue(all(r[9]==r[23]==0 for r in P.boundary_vectors()))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_corruption_between_target_and_master_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);vectors=d/'vectors.txt'
            vectors.write_text(''.join(' '.join(format(x,'x') for x in row)+'\n' for row in P.boundary_vectors()))
            build=subprocess.run(['iverilog','-g2012','-s',P.TOP,'-Pmemory_order_tb.CORRUPT_RDATA=1','-o',str(d/'sim.vvp'),*[str(p) for p in P.SOURCES]],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            result=subprocess.run(['vvp',str(d/'sim.vvp'),f'+VECTORS={vectors}',f'+WAVE={d/"wave.vcd"}'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('CHECK_FAIL ORDER_READ',result.stdout);self.assertNotIn('RESULT PASS',result.stdout)

if __name__=='__main__':unittest.main()
