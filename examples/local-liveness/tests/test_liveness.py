from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reference import graph_result
from witness import FIELDS,read_vcd,replay

def rows():
    result=[]
    for step in range(4):
        row={k:0 for k in FIELDS};row.update(step=step,rst_n=int(step>0),ready=3 if step<2 else 1)
        if step==1:row['request']=2
        if step>=2:row.update(state=5,pending=2,owed=1,choose=int(step==2))
        if step==3:row.update(active=1,snapshot=5)
        result.append(row)
    return result

def vcd(data):
    names={'step':('!','smt_step',32),**{k:('n'+str(i),k,w) for i,(k,w) in enumerate(FIELDS.items())}}
    text='$scope module liveness_formal $end\n'+''.join('$var wire %d %s %s $end\n'%(w,c,n) for c,n,w in names.values())+'$upscope $end\n$enddefinitions $end\n'
    for row in data:text+='#%d\n'%(row['step']*10)+''.join('b'+format(row[k],'b')+' '+c+'\n' for k,(c,n,w) in names.items())
    return text
class LivenessTests(unittest.TestCase):
    def test_graph_distinguishes_fairness_starvation_and_lost_request(self):
        self.assertTrue(graph_result(0,True)['success'])
        self.assertFalse(graph_result(0,False)['success'])
        self.assertFalse(graph_result(1,True)['success'])
        self.assertFalse(graph_result(2,True)['success'])
        self.assertEqual(graph_result(0,True)['states'],8)
        self.assertEqual(graph_result(2,True)['states'],12)
    def test_real_closed_walk_replayed_from_inputs(self):
        data=read_vcd(vcd(rows()));result=replay(data,0,False)
        self.assertEqual((result['prefix_steps'],result['loop_steps'],result['fair_opportunities']),(2,1,0))
        with self.assertRaises(ValueError):replay(data,0,True)
    def test_forged_state_handshake_monitor_or_reset_fails(self):
        for field,value in [('state',7),('grant',2),('ready',3),('snapshot',4),('rst_n',0)]:
            data=rows();data[-1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):replay(data,0,False)
    def test_truncated_unknown_or_duplicate_vcd_is_not_a_witness(self):
        text=vcd(rows())
        for bad in (text.replace('b101 n4','bx n4'),text.replace('b101 n4\n',''),text.replace('$enddefinitions $end',''),text+text):
            with self.subTest(bad=bad),self.assertRaises((ValueError,IndexError)):read_vcd(bad)
    def test_no_closed_walk_cannot_be_counted_as_failure(self):
        with self.assertRaises(ValueError):replay(rows()[:3],0,False)
if __name__=='__main__':unittest.main()
