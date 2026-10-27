from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-formal-replay')
class WitnessTests(unittest.TestCase):
    def document(self):
        signals=[dict(path=['\\'+name],width=width,offset=0,init_only=False) for name,width in [('clk',1),('rst_n',1),('valid',1),('ready',1),('data',4)]]
        signals.append(dict(path=['\\dut','\\state'],width=2,offset=0,init_only=True))
        return dict(format='Yosys Witness Trace',clocks=[dict(path=['\\clk'],edge='posedge',offset=0)],signals=signals,steps=[dict(bits='1100000000'),dict(bits='10010110')])
    def test_only_top_inputs_and_step_specific_bit_layout(self):
        self.assertEqual(P.witness_inputs(self.document()),[[0,0,0,0],[1,1,0,9]])
    def test_unknown_top_input_is_not_filled_with_zero(self):
        d=self.document();d['steps'][1]['bits']='x0010110'
        with self.assertRaises(ValueError):P.witness_inputs(d)
    def test_missing_reset_or_truncated_step_rejected(self):
        for bits in ('1100000010','0000'):
            d=self.document();d['steps'][0]['bits']=bits
            with self.assertRaises(ValueError):P.witness_inputs(d)
    def test_oracle_snapshots_old_state_before_synchronous_reset(self):
        rows=P.oracle([[0,0,0,0],[1,1,0,9],[0,0,0,0],[1,0,1,0]],2)
        self.assertEqual(rows[2][4:],[1,1,9]);self.assertEqual(rows[3][4:],[1,0,0])
if __name__=='__main__':unittest.main()
