import importlib.util
from pathlib import Path
import re
import unittest
s=importlib.util.spec_from_file_location('mc_under_test',Path(__file__).resolve().parents[1]/'run.py');M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
DELAY={0:15,1:20,2:5}
def fixture(guided=True):
    lines=[];stamp=0;identity=0;processed=[];arrivals=[]
    def event(kind,id=0,data=0,mask=0,after=10):
        nonlocal stamp;stamp+=after;lines.append(f'MC_OBS kind={kind} t={stamp} id={id} data={data} mask={mask}')
        processed.append(f'MC_PROCESS kind={kind} t={stamp} id={id} data={data} mask={mask}');arrivals.append((stamp+DELAY[kind],kind,stamp))
    def source():
        nonlocal identity;identity+=1;lines.append(f'MC_ISSUED id={identity} data=85');event(0,identity,85,after=100)
    event(2,mask=2);event(2,mask=0)
    for masks in ([1,0],[2,0],[3,2,0],[3,1,0]):
        source()
        for mask in masks:event(2,mask=mask,after=100)
    source();event(1,identity,85^0x3c,after=100);event(2,mask=1,after=5 if guided else 100);event(2,mask=0,after=100)
    source();event(2,mask=2,after=5 if guided else 100);event(2,mask=0,after=100)
    for _ in range(15):source();event(1,identity,85^0x3c,after=100)
    arrive=[f'MC_ARRIVE kind={kind} t={t} at={at}' for at,kind,t in sorted(arrivals)]
    return '\n'.join(lines+arrive+processed)+'\n'
class MulticlockEvidenceTests(unittest.TestCase):
    def test_complete_ledger(self):self.assertTrue(M.ledger(fixture(),0))
    def test_notification_order_does_not_change_clock_order(self):
        log=fixture();issued=[l for l in log.splitlines() if l.startswith('MC_ISSUED')];events=[l for l in log.splitlines() if l.startswith('MC_OBS')];rest=[l for l in log.splitlines() if l.startswith(('MC_PROCESS','MC_ARRIVE'))]
        self.assertEqual(M.ledger(log,0),M.ledger('\n'.join(issued+events[::-1]+rest)+'\n',0))
    def test_arrival_order_processing_is_rejected(self):
        log=fixture();lines=log.splitlines();processed=[i for i,l in enumerate(lines) if l.startswith('MC_PROCESS')]
        reset=next(i for i in processed if 'kind=2' in lines[i] and 'kind=1' in lines[i-1] and 'mask=1' in lines[i])
        lines[reset-1],lines[reset]=lines[reset],lines[reset-1]
        with self.assertRaisesRegex(ValueError,'scoreboard order'):M.ledger('\n'.join(lines)+'\n',0)
    def test_run_without_a_real_notification_inversion_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'never overtook'):M.ledger(fixture(guided=False),0)
    def test_missing_processing_or_notification_record_is_rejected(self):
        log=fixture()
        for prefix in ('MC_PROCESS','MC_ARRIVE'):
            line=next(l for l in log.splitlines() if l.startswith(prefix))
            with self.subTest(prefix=prefix),self.assertRaises(ValueError):M.ledger(log.replace(line+'\n','',1),0)
    def test_cancelled_response_rejected(self):
        with self.assertRaises(ValueError):M.ledger(fixture()+'MC_OBS kind=1 t=99999 id=1 data=105 mask=0\n',0)
    def test_duplicate_clock_record_rejected(self):
        log=fixture();event=next(l for l in log.splitlines() if l.startswith('MC_OBS kind=0'))
        with self.assertRaises(ValueError):M.ledger(log+event+'\n',0)
    def test_malformed_record_rejected(self):
        with self.assertRaises(ValueError):M.ledger(fixture()+'MC_OBS malformed\n',0)
    def test_wrong_value_rejected(self):
        with self.assertRaises(ValueError):M.ledger(fixture().replace('data=105','data=104',1),0)
    def test_missing_reset_rejected(self):
        log=fixture();line=next(l for l in log.splitlines() if l.startswith('MC_OBS kind=2') and l.endswith('mask=1'))
        with self.assertRaises(ValueError):M.ledger(log.replace(line+'\n','',1),0)
    def test_rtl_defects_and_scoreboard_order_have_required_labels(self):
        self.assertEqual(dict(M.MUTANTS),{1:'MC_DATA',2:'MC_STALE',3:'MC_RELEASE',4:'MC_CHANNEL',5:'MC_CHANNEL'})
if __name__=='__main__':unittest.main()
