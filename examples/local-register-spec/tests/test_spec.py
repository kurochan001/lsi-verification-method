from pathlib import Path
import copy,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-register-spec')
class SpecificationTests(unittest.TestCase):
    def test_independent_contract_rejects_shared_reset_error(self):
        c=json.loads((P.HERE/'contract.json').read_text());wrong=copy.deepcopy(c);wrong[0]['reset']+=1
        self.assertFalse(P.same_contract(wrong,c));self.assertTrue(P.same_contract(list(reversed(c)),c))
    def test_changed_offset_width_and_access_rejected(self):
        c=json.loads((P.HERE/'contract.json').read_text())
        for field,value in [('address',12),('width',7),('access','RO')]:
            wrong=copy.deepcopy(c);wrong[0][field]=value;self.assertFalse(P.same_contract(wrong,c))
    def test_stimulus_seed_and_fixed_competition(self):
        self.assertEqual(P.operations(17,5),P.operations(17,5));self.assertNotEqual(P.operations(17,5),P.operations(18,5))
        self.assertIn([8,1,3,3,3],P.operations(17,0))
    def test_real_systemrdl_elaboration_matches_contract(self):
        generator=P.E.load('test_rdl_generator',P.HERE/'generate.py')
        self.assertTrue(P.same_contract(generator.model(P.HERE/'registers.rdl'),json.loads((P.HERE/'contract.json').read_text())))
    def test_unsupported_structure_and_properties_are_rejected(self):
        generator=P.E.load('test_rdl_generator2',P.HERE/'generate.py')
        with tempfile.TemporaryDirectory() as tmp:
            source=(P.HERE/'registers.rdl').read_text()
            cases=["addrmap bad {reg {field {sw=rw;hw=r;reset=0;} a[0:0];field {sw=rw;hw=r;reset=0;} b[1:1];} cfg;};",
                   source.replace("sw=rw;hw=r;reset=8'h12", "sw=rw;hw=r;singlepulse=true;reset=0").replace('value[7:0]','value[0:0]'),
                   source.replace("sw=rw;hw=r;reset=8'h12", "sw=rw;hw=rw;reset=8'h12"),
                   source.rsplit('};',1)[0]+"regfile {reg {field {sw=rw;hw=r;reset=0;} value[7:0];} extra;} nested @ 0x100;};"]
            for i,text in enumerate(cases):
                with self.subTest(case=i):
                    p=Path(tmp)/'bad.rdl';p.write_text(text)
                    with self.assertRaises(ValueError):generator.model(p)
    def test_pending_requires_explicit_event_and_precedence_contract(self):
        generator=P.E.load('test_pending_policy',P.HERE/'generate.py')
        source=(P.HERE/'registers.rdl').read_text()
        changes=[('precedence=hw;',''),('precedence=hw;','precedence=sw;'),('stickybit;',''),('stickybit;','intr;stickybit;'),('stickybit;','stickybit=false;')]
        with tempfile.TemporaryDirectory() as tmp:
            for before,after in changes:
                with self.subTest(change=(before,after)):
                    self.assertIn(before,source)
                    p=Path(tmp)/'policy.rdl';p.write_text(source.replace(before,after))
                    with self.assertRaises(ValueError):generator.model(p)
if __name__=='__main__':unittest.main()
