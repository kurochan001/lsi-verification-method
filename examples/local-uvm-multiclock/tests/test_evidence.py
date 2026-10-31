import importlib.util
from pathlib import Path
import unittest
s=importlib.util.spec_from_file_location('mc_under_test',Path(__file__).resolve().parents[1]/'run.py');M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
def fixture():
    lines=[];stamp=0;identity=0
    def event(kind,id=0,data=0,mask=0):
        nonlocal stamp;stamp+=10;lines.append(f'MC_OBS kind={kind} t={stamp} id={id} data={data} mask={mask}')
    def source():
        nonlocal identity;identity+=1;lines.append(f'MC_ISSUED id={identity} data=85');event(0,identity,85)
    event(2,mask=2);event(2,mask=0)
    for masks in ([1,0],[2,0],[3,2,0],[3,1,0]):
        source()
        for mask in masks:event(2,mask=mask)
    for _ in range(13):source();event(1,identity,85^0x3c)
    return '\n'.join(lines)+'\n'
class MulticlockEvidenceTests(unittest.TestCase):
    def test_complete_ledger(self):self.assertTrue(M.ledger(fixture(),0))
    def test_notification_order_does_not_change_clock_order(self):
        log=fixture();issued=[l for l in log.splitlines() if l.startswith('MC_ISSUED')];events=[l for l in log.splitlines() if l.startswith('MC_OBS')]
        self.assertEqual(M.ledger(log,0),M.ledger('\n'.join(issued+events[::-1])+'\n',0))
    def test_cancelled_response_rejected(self):
        with self.assertRaises(ValueError):M.ledger(fixture()+'MC_OBS kind=1 t=9999 id=1 data=105 mask=0\n',0)
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
if __name__=='__main__':unittest.main()
