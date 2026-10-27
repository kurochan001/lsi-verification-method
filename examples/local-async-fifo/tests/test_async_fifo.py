from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
FIFO=load_example('local-async-fifo')


def command(w=0,r=0,rst=1,we=0,data=0,re=0):return [w,r,rst,we,data,re,0]


class AsyncFifoTest(unittest.TestCase):
    def test_queue_data_and_independent_read_flag_latency(self):
        commands=[command(rst=0),command(w=1,we=1,data=0xa5),command()]
        for _ in range(5):commands.extend([command(r=1,re=1),command(re=1)])
        rows,counts=FIFO.reference(commands,4,2)
        self.assertEqual(counts,dict(writes=1,reads=1,blocked_writes=0,blocked_reads=4))
        self.assertEqual([rows[i][8] for i in (3,5,7,9,11)],[1,1,0,1,1])
        self.assertEqual(rows[9][9:],[1,0xa5])
        self.assertEqual(rows[11][9:],[0,0xa5])

    def test_common_reset_flushes_unread_data(self):
        commands=[command(rst=0),command(w=1,we=1,data=0x99),command(),command(rst=0)]
        for _ in range(6):commands.extend([command(r=1,re=1),command(re=1)])
        rows,counts=FIFO.reference(commands,4,2)
        self.assertEqual(counts['writes'],1);self.assertEqual(counts['reads'],0)
        self.assertTrue(all(r[8:]==[1,0,0] for r in rows[3:]))

    def test_full_blocks_writes_and_preserves_original_data(self):
        commands=[command(rst=0)]
        for value in range(6):commands.extend([command(w=1,we=1,data=value),command()])
        for _ in range(12):commands.extend([command(r=1,re=1),command(re=1)])
        rows,counts=FIFO.reference(commands,4,2)
        accepted=[r[10] for i,r in enumerate(rows) if r[1] and (i==0 or not rows[i-1][1]) and r[9]]
        self.assertEqual(accepted,[0,1,2,3])
        self.assertEqual(counts['blocked_writes'],2)

    def test_jitter_schedule_reproducibility_and_positive_half_periods(self):
        a=FIFO.schedule(17,4,2,3,600)
        self.assertEqual(a,FIFO.schedule(17,4,2,3,600))
        self.assertNotEqual(a,FIFO.schedule(18,4,2,3,600))
        for index,nominal in [(0,3),(1,5)]:
            transitions=[i for i in range(1,len(a)) if a[i][index]!=a[i-1][index]]
            intervals={b-a for a,b in zip(transitions,transitions[1:])}
            self.assertEqual(intervals,{nominal-1,nominal,nominal+1})

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_all_rtl_configurations_mutations_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-async-fifo',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,FIFO.CONFIGS,17,24)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_each_demo_fault_fails_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-async-fifo',out,'--configuration','depth4-sync2','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'depth4-sync2-boundaries-clocks/result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
