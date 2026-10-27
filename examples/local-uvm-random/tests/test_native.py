from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-uvm-random')
class NativeTests(unittest.TestCase):
    def rows(self):
        return ["C '\x01t\x02covergroup\x01f\x02"+str(P.HERE/'tb/random_pkg.sv')+"\x01h\x02"+name+"' 1" for name in sorted(P.EXPECTED_BINS)]
    def parse(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'coverage.dat';p.write_text('\n'.join(rows)+'\n');return P.native(p)
    def test_all_native_bins_required(self):
        self.assertEqual(len(self.parse(self.rows())),24)
        with self.assertRaises(ValueError):self.parse(self.rows()[:-1])
    def test_duplicate_and_zero_hit_bins_rejected(self):
        rows=self.rows()
        for changed in (rows+[rows[0]],[rows[0][:-1]+'0',*rows[1:]]):
            with self.assertRaises(ValueError):self.parse(changed)
    def test_random_trace_constraints_are_checked(self):
        self.assertEqual(P.random_trace('RANDOM addr=8 write=1 data=0000000f events=3\n',1),[[8,1,15,3]])
        with self.assertRaises(ValueError):P.random_trace('RANDOM addr=8 write=1 data=00000010 events=3\n',1)
    def test_missing_unknown_and_duplicate_random_operations_rejected(self):
        for log in ('','RANDOM addr=0 write=1 data=xxxxxxxx events=3\n','RANDOM addr=1 write=1 data=00000000 events=3\n'):
            with self.assertRaises(ValueError):P.random_trace(log,1)
if __name__=='__main__':unittest.main()
