import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
s=importlib.util.spec_from_file_location('outstanding_under_test',Path(__file__).resolve().parents[1]/'run.py');R=importlib.util.module_from_spec(s);s.loader.exec_module(R)

def fixture(orders=((2,0,3,1),(1,3,0,2)),same_edge=True,draining=True,probe_delay=7):
    """Two rounds of the planned shape, with a cancelled batch after the first."""
    state=17;token=0;issued=[];observed=['OO_RESET cycle=1 rst=1'];cycle=2
    def accept(identity,delay=0,advance=True):
        nonlocal state,token,cycle
        state=(state*1664525+1013904223)&0xffffffff;token+=1;row=(identity,token,((state>>19)&31)<<3|delay);issued.append(row)
        observed.append('OO_OBS kind=0 cycle=%d id=%d token=%d data=%d'%(cycle,*row));cycle+=int(advance);return dict(row=row,cycle=cycle-int(advance))
    def complete(item,latency=None):
        nonlocal cycle
        identity,number,data=item['row'];cycle=max(cycle,item['cycle']+(latency if latency is not None else (data&7)+2))
        observed.append('OO_OBS kind=1 cycle=%d id=%d token=%d data=%d'%(cycle,identity,number,(3*data+identity)%256));cycle+=1
    for r,order in enumerate(orders):
        batch=[accept(i) for i in order]
        for item in reversed(batch):complete(item)
        if draining:
            first=accept(0,7);second=accept(1);complete(second);third=accept(2);complete(first,12);fourth=accept(3);complete(third);fifth=accept(0);complete(fourth);sixth=accept(1);complete(fifth);complete(sixth)
        else:
            for i in (0,1,2,3,0,1):complete(accept(i))
        complete(accept(r,probe_delay))
        held=accept((r+1)%4);other=accept((r+2)%4);complete(held)
        if not draining:complete(other)
        retry=accept((r+1)%4)
        if draining:complete(other)
        complete(retry)
        x=accept((r+3)%4)
        if same_edge:
            cycle=x['cycle']+2;z=accept(r,advance=False);complete(x);complete(z)
        else:
            complete(x);complete(accept(r))
        if r==0:
            for i in order:accept(i)
            observed+=['OO_RESET cycle=%d rst=0'%cycle,'OO_RESET cycle=%d rst=1'%(cycle+1)];cycle+=2
    lines=['OO_ISSUED id=%d token=%d data=%d'%row for row in issued]+observed
    lines+=['OO_COMPLETE accepted=36 produced=32 cancelled=4 epoch=1 peak=4 overtakes=8 reused=32 pending=0']
    return '\n'.join(lines)+'\n'
class OutstandingTests(unittest.TestCase):
    def test_reordering_id_reuse_and_reset_cancellation(self):
        counts=R.ledger(fixture(),2,17);self.assertEqual((counts['peak'],counts['cancelled'],counts['overtakes'],counts['delay_overtakes']),(4,4,8,2))
        self.assertEqual((counts['batch_orders'],counts['reply_orders'],counts['concurrent'],counts['tight_latency']),(2,2,2,2));self.assertGreaterEqual(counts['draining'],2)
    def test_missing_duplicate_stale_and_wrong_value_are_rejected(self):
        log=fixture();completion=next(l for l in log.splitlines() if l.startswith('OO_OBS kind=1'));number=int(re.search(r'token=(\d+)',completion)[1])
        for bad in (log.replace(completion+'\n',''),log+completion+'\n',log.replace(completion,completion.replace('token=%d'%number,'token=%d'%(number+4))),log.replace(completion,completion.rsplit('data=',1)[0]+'data=999')):
            with self.subTest(bad=bad[-120:]):
                with self.assertRaises(ValueError):R.ledger(bad,2,17)
    def test_wrong_seed_and_forged_summary_are_rejected(self):
        with self.assertRaises(ValueError):R.ledger(fixture(),2,18)
        with self.assertRaises(ValueError):R.ledger(fixture().replace('cancelled=4','cancelled=0'),2,17)
    def test_cancellation_cannot_be_reported_as_completion(self):
        # The expected pulse must be observed; dropping either edge is invalid.
        line=next(l for l in fixture().splitlines() if l.startswith('OO_RESET') and l.endswith('rst=0'))
        with self.assertRaises(ValueError):R.ledger(fixture().replace(line+'\n',''),2,17)
    def test_response_before_the_internal_delay_is_rejected(self):
        log=fixture();line=next(l for l in log.splitlines() if l.startswith('OO_OBS kind=0') and int(l.rsplit('data=',1)[1])&7==7)
        cycle,identity,number,data=map(int,re.fullmatch(r'OO_OBS kind=0 cycle=(\d+) id=(\d+) token=(\d+) data=(\d+)',line).groups())
        answer=next(l for l in log.splitlines() if l.startswith('OO_OBS kind=1') and ' token=%d '%number in l)
        with self.assertRaisesRegex(ValueError,'completion transaction'):R.ledger(log.replace(answer,re.sub(r'cycle=\d+','cycle=%d'%(cycle+8),answer)),2,17)
    def test_one_fixed_order_cannot_satisfy_the_order_goal(self):
        with self.assertRaisesRegex(ValueError,'ID-order'):R.ledger(fixture(orders=((2,0,3,1),(2,0,3,1))),2,17)
    def test_stimulus_without_draining_same_edge_or_delay_probe_is_incomplete(self):
        for options in (dict(same_edge=False),dict(draining=False),dict(probe_delay=0)):
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'ID-order, draining'):R.ledger(fixture(**options),2,17)
    def test_every_rtl_defect_has_a_required_label(self):
        self.assertEqual(R.MUTANTS,{1:'OO_DATA',2:'OO_TOKEN',3:'OO_UNKNOWN',4:'OO_UNKNOWN',5:'OO_BUSY',6:'OO_TOKEN',7:'OO_LATENCY',8:'OO_HOLD'})
    def test_native_database_must_match_observed_transactions(self):
        counts=R.ledger(fixture(),2,17);values=dict(cp_accept=36,cp_response=32,cp_reuse=32,cp_ooo=8,cp_reset=1,cp_recovery=16,cp_concurrent=2,cp_stall=2,cp_full=2,cp_busy=2,cp_stall_accept=2)
        log=fixture()+''.join(('OO_COVER '+k+'\n')*v for k,v in values.items())
        db=''.join("C '\x01t\x02user\x01o\x02"+k+'\x01h\x02TOP.top.'+k+'\x01f\x02'+str(R.HERE/'tb/top.sv')+"' "+str(v)+'\n' for k,v in values.items())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'coverage.dat';path.write_text(db);self.assertEqual(R.native(path,log,counts,2),values)
            path.write_text(db.replace("' 36\n","' 35\n"))
            with self.assertRaises(ValueError):R.native(path,log,counts,2)
if __name__=='__main__':unittest.main()
