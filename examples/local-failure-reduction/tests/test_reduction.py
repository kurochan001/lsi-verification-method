from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-failure-reduction')
class ReductionTests(unittest.TestCase):
    def test_keeps_required_ordered_pair(self):
        def fails(xs):return 'open' in xs and 'close' in xs and xs.index('open')<xs.index('close')
        result=P.ddmin(['idle','open','noise','close','idle'],fails)
        self.assertEqual(result,['open','close'])
    def test_no_failure_can_be_created_by_deletion(self):
        seq=[1,2,3];self.assertEqual(P.ddmin(seq,lambda xs:False),seq)
    def test_infrastructure_exception_is_not_a_reproducer(self):
        def oracle(xs):raise RuntimeError('timeout')
        with self.assertRaises(RuntimeError):P.ddmin([1,2],oracle)
    def test_seed_and_regenerated_handshakes(self):
        actions=P.operations(17,24);self.assertEqual(actions,P.operations(17,24));self.assertNotEqual(actions,P.operations(18,24))
        axis=load_example('local-axis');rows=P.rows(axis,[dict(op='beat',data=0,keep=1,last=0)])
        self.assertEqual(axis.counts(rows)['delivered'],1);self.assertEqual(rows[0][0],0)
    def test_noise_can_be_removed_to_one_action(self):
        result=P.ddmin([0,0,1,0,0],lambda xs:1 in xs);self.assertEqual(result,[1])
if __name__=='__main__':unittest.main()
