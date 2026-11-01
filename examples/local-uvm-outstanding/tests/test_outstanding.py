import importlib.util
from pathlib import Path
import tempfile
import unittest
s=importlib.util.spec_from_file_location('outstanding_under_test',Path(__file__).resolve().parents[1]/'run.py');R=importlib.util.module_from_spec(s);s.loader.exec_module(R)

def fixture():
    seed=17;state=seed;issued=[];lines=[]
    for i in range(12):
        state=(state*1664525+1013904223)&0xffffffff;issued.append((i%4,i+1,(state>>16)&255))
    lines+=['OO_ISSUED id=%d token=%d data=%d'%row for row in issued];lines+=['OO_RESET cycle=1 rst=1'];cycle=2
    for batch in range(3):
        rows=issued[4*batch:4*batch+4]
        for identity,token,data in rows:lines+=['OO_OBS kind=0 cycle=%d id=%d token=%d data=%d'%(cycle,identity,token,data)];cycle+=1
        if batch==1:lines+=['OO_RESET cycle=%d rst=0'%cycle,'OO_RESET cycle=%d rst=1'%(cycle+1)];cycle+=2
        else:
            for identity,token,data in reversed(rows):lines+=['OO_OBS kind=1 cycle=%d id=%d token=%d data=%d'%(cycle,identity,token,(3*data+identity)%256)];cycle+=1
    lines+=['OO_COMPLETE accepted=12 produced=8 cancelled=4 epoch=1 peak=4 overtakes=6 reused=8 pending=0']
    return '\n'.join(lines)+'\n'
class OutstandingTests(unittest.TestCase):
    def test_reordering_id_reuse_and_reset_cancellation(self):
        counts=R.ledger(fixture(),2,17);self.assertEqual((counts['peak'],counts['cancelled'],counts['overtakes']),(4,4,6))
    def test_missing_duplicate_stale_and_wrong_value_are_rejected(self):
        log=fixture();completion=next(l for l in log.splitlines() if l.startswith('OO_OBS kind=1'))
        for bad in (log.replace(completion+'\n',''),log+completion+'\n',log.replace(completion,completion.replace('token=4','token=8')),log.replace(completion,completion.rsplit('data=',1)[0]+'data=999')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):R.ledger(bad,2,17)
    def test_wrong_seed_and_forged_summary_are_rejected(self):
        with self.assertRaises(ValueError):R.ledger(fixture(),2,18)
        with self.assertRaises(ValueError):R.ledger(fixture().replace('cancelled=4','cancelled=0'),2,17)
    def test_cancellation_cannot_be_reported_as_completion(self):
        # The expected pulse must be observed; dropping either edge is invalid.
        line=next(l for l in fixture().splitlines() if l.startswith('OO_RESET') and l.endswith('rst=0'))
        with self.assertRaises(ValueError):R.ledger(fixture().replace(line+'\n',''),2,17)
    def test_native_database_must_match_observed_transactions(self):
        counts=R.ledger(fixture(),2,17);values=dict(cp_accept=12,cp_response=8,cp_reuse=8,cp_ooo=6,cp_reset=1,cp_recovery=4,cp_stall=2,cp_full=2)
        log=fixture()+''.join(('OO_COVER '+k+'\n')*v for k,v in values.items())
        db=''.join("C '\x01t\x02user\x01o\x02"+k+'\x01h\x02TOP.top.'+k+'\x01f\x02'+str(R.HERE/'tb/top.sv')+"' "+str(v)+'\n' for k,v in values.items())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'coverage.dat';path.write_text(db);self.assertEqual(R.native(path,log,counts,2),values)
            path.write_text(db.replace("' 12\n","' 11\n"))
            with self.assertRaises(ValueError):R.native(path,log,counts,2)
if __name__=='__main__':unittest.main()
