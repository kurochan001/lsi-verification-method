"""Independent byte-oracle anchors and real HDL checker positive/negative tests."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ram_test_runner',HERE/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
M=R.M


class OracleTests(unittest.TestCase):
    def test_known_byte_lanes_and_native_byte_views(self):
        p=M.Plan();p.step(rst=0);p.initialize()
        p.write(2,0x11223344,native=True)
        self.assertEqual(p.memory.bytes[8:12],[0x44,0x33,0x22,0x11])
        p.read(2);self.assertEqual(p.rows[-1][21],0x11223344)
        p.write(2,0x00aa0000,mask=4);p.read(2,native=True)
        self.assertEqual(p.rows[-1][21],0x11aa3344)
        p.write(2,0xffffffff,mask=0);p.read(2)
        self.assertEqual(p.rows[-1][21],0x11aa3344)

    def test_read_during_write_modes_have_distinct_known_outputs(self):
        for mode,expected in ((0,0x11223344),(1,0x112233aa),(2,0x55667788)):
            with self.subTest(mode=mode):
                p=M.Plan(kind=1,mode=mode);p.initialize()
                p.write(1,0x11223344);p.write(2,0x55667788);p.read(2)
                p.step(a=p.request(1,True,True,0xaa,1),b=p.request(1,native=True))
                self.assertEqual(p.rows[-1][21],expected)
                self.assertEqual(p.rows[-1][19],1)
                p.read(1);self.assertEqual(p.rows[-1][21],0x112233aa)

    def test_collision_rejects_both_writes_even_with_disjoint_masks(self):
        p=M.Plan();p.initialize();before=p.memory.bytes[:]
        p.step(a=p.request(1,True,False,0x55,1),b=p.request(1,True,True,0xaa00,2))
        self.assertEqual(p.rows[-1][15:18],[1,1,1])
        self.assertEqual(p.memory.bytes,before)

    def test_bad_addresses_retain_data_and_reset_retains_initialized_memory(self):
        p=M.Plan(width=64,depth=13);p.initialize();before=p.memory.bytes[:]
        for address in (p.base+1,p.base-8,p.base+13*8):
            p.step(a=(1,1,0,address,p.maximum,p.full))
            self.assertEqual(p.rows[-1][15],1)
        p.step(a=p.request(1,True,True,p.maximum),rst=0)
        self.assertEqual(p.memory.bytes,before)
        self.assertEqual(p.rows[-1][20:22],[0,0])
        p.read(12);self.assertEqual(p.rows[-1][21],p.pattern(12))

    def test_uninitialized_reads_are_not_claimed_to_be_zero(self):
        p=M.Plan()
        with self.assertRaisesRegex(ValueError,'before byte initialization'):p.read(0)

    def test_random_vectors_replay_and_completion_evidence_is_strict(self):
        args=(64,8,2,1,256)
        self.assertEqual(M.stimulus(*args,17),M.stimulus(*args,17))
        self.assertNotEqual(M.stimulus(*args,17),M.stimulus(*args,18))
        good='COUNT rows=2\n';R.completion(good,{'rows':2})
        for bad in ('',good+good,good+'COUNT extra=0\n',good+'WARNING: test\n'):
            with self.assertRaises(ValueError):R.completion(bad,{'rows':2})


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus Verilog required')
class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)
        self.args=SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False)
        self.sim=R.Simulator(self.args,self.out)

    def test_all_port_types_modes_widths_and_non_power_of_two_depth(self):
        configs=R.configurations(SimpleNamespace(width=32,depth=16,base=256))
        for name,pars in configs.items():
            with self.subTest(name=name):
                result=self.sim.execute(name,pars,R.rows_for(pars,17,8),17)
                self.assertEqual(result['status'],'pass',result)
                self.assertFalse(R.required_goals(pars)-set(result['coverage']))
                self.assertNotIn('WARNING:',(self.out/name/'simulation.log').read_text())

    def test_every_mutation_fails_through_the_intended_checker(self):
        for mutation in range(1,13):
            with self.subTest(mutation=mutation):
                pars=dict(DATA_W=64 if mutation==3 else 32,DEPTH=16,KIND=2,RDW_MODE=1,BASE_ADDR=264 if mutation==12 else 256)
                label='RAM_STATUS' if mutation in (4,5,10) else 'RAM_DATA'
                result=self.sim.execute(f'm{mutation}',pars,R.rows_for(pars,17,0),17,mutation,label)
                self.assertEqual(result['status'],'detected',result)

    def test_a_symmetric_address_bug_survives_weak_self_readback_but_not_cross_view(self):
        pars=dict(DATA_W=32,DEPTH=16,KIND=2,RDW_MODE=1,BASE_ADDR=256)
        weak=M.Plan();weak.step(rst=0);weak.initialize(native=False)
        for index in range(weak.depth):weak.read(index,native=False)
        result=self.sim.execute('weak-self-readback',pars,weak.rows,17,mutation=11)
        self.assertEqual(result['status'],'pass',result)
        print('EXPECTED_LIMITATION symmetric_address_permutation_survives_self_readback')
        strong=self.sim.execute('cross-view',pars,R.rows_for(pars,17,0),17,11,'RAM_DATA')
        self.assertEqual(strong['status'],'detected',strong)
        hidden=self.sim.execute('aligned-base-hides-error',pars,R.rows_for(pars,17,0),17,12)
        self.assertEqual(hidden['status'],'pass',hidden)
        print('EXPECTED_LIMITATION base_subtraction_error_hidden_by_index_wrap')
        offset=dict(pars,BASE_ADDR=264)
        exposed=self.sim.execute('offset-base',offset,R.rows_for(offset,17,0),17,12,'RAM_DATA')
        self.assertEqual(exposed['status'],'detected',exposed)

    def test_zero_comparisons_cannot_pass_and_unknown_data_is_a_failure(self):
        pars=dict(DATA_W=32,DEPTH=16,KIND=0,RDW_MODE=0,BASE_ADDR=256)
        empty=self.sim.execute('empty',pars,[],17)
        self.assertNotEqual(empty['status'],'pass')
        original=HERE/'rtl/ram_sp.sv';mutated=self.out/'ram_sp.sv'
        mutated.write_text(original.read_text().replace('rdata<=memory[address];',"rdata<={DATA_W{1'bx}};"))
        with patch.object(R,'SOURCES',[mutated if p==original else p for p in R.SOURCES]):
            other=R.Simulator(self.args,self.out)
            # Isolate the build cache and binary from the already-built empty case.
            child=self.out/'unknown-build';child.mkdir();other.out=child
            result=other.execute('unknown',pars,R.rows_for(pars,17,0),17,0,'RAM_DATA')
        self.assertEqual(result['status'],'detected',result)
        self.assertIn('actual=xxxxxxxx',(child/'unknown/simulation.log').read_text())
        mutated.write_text(original.read_text().replace('always @(posedge clk)','always @*'))
        with patch.object(R,'SOURCES',[mutated if p==original else p for p in R.SOURCES]):
            child=self.out/'async-build';child.mkdir();other=R.Simulator(self.args,child)
            result=other.execute('async-read',pars,R.rows_for(pars,17,0),17,0,'RAM_LATENCY')
        self.assertEqual(result['status'],'detected',result)


if __name__=='__main__':unittest.main()
