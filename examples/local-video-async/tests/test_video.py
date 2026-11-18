"""Oracle anchors, real HDL runs, replay, and checker negative cases."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('video_test_runner',HERE/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
M=R.M


class OracleTests(unittest.TestCase):
    def test_known_black_white_gray_and_clipping(self):
        self.assertEqual(M.csc(16,128,128),(0,0,0))
        self.assertEqual(M.csc(235,128,128),(255,255,255))
        self.assertEqual(M.csc(128,128,128),(130,130,130))
        self.assertEqual(M.csc(81,90,240),(255,0,0))
        self.assertEqual(M.csc(0,0,0),(0,135,0))
        self.assertEqual(M.csc(255,255,255),(255,125,255))

    def test_straight_alpha_endpoints_and_rounding(self):
        fg,bg=(240,33,128),(13,77,241)
        self.assertEqual(M.blend(fg,bg,0),bg)
        self.assertEqual(M.blend(fg,bg,255),fg)
        self.assertEqual(M.blend((255,255,255),(0,0,0),127),(127,127,127))
        self.assertEqual(M.blend((255,255,255),(0,0,0),128),(128,128,128))
        self.assertEqual(M.blend((1,127,254),(255,0,17),1),(254,0,18))

    def test_key_exact_match_and_each_near_miss_keep_markers(self):
        bg=(17,91,204)
        for channel in range(4):
            color=list(M.KEY)
            if channel<3:color[channel]+=1
            p=M.pack(color,255,bg,True,True)
            keyed,_,output=M.transform(p)
            self.assertEqual(keyed>>56,3)
            self.assertEqual((keyed>>24)&255,255 if channel<3 else 0)
            if channel==3:self.assertEqual(output&0xffffff,0x115bcc)

    def test_seed_epochs_and_metadata_are_independent(self):
        a=M.image_packets(9,5,2,17)
        self.assertEqual(a,M.image_packets(9,5,2,17))
        self.assertNotEqual(a,M.image_packets(9,5,2,18))
        self.assertNotEqual(a,M.image_packets(9,5,2,17,1))
        self.assertEqual(sum((p>>57)&1 for p in a),2)
        self.assertEqual(sum((p>>56)&1 for p in a),10)

    def test_invalid_components_are_rejected(self):
        for v in (-1,256,1.5):
            with self.assertRaises(ValueError):M.csc(v,128,128)
            with self.assertRaises(ValueError):M.blend((0,1,v),(1,2,3),128)

    def test_completion_rejects_zero_duplicate_failure_and_truncation(self):
        good='COUNT accepted_in=4\nRESULT PASS checks=7\n'
        self.assertEqual(R.completion(good),(7,{'accepted_in':4}))
        for bad in ('',good.replace('checks=7','checks=0'),good+good,good+'CHECK_FAIL bad\n',good+'FATAL: bad\n',good+'WARNING: excess digits\n',good+'COUNT accepted_in=4\n'):
            with self.assertRaises(ValueError):R.completion(bad)


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus Verilog required')
class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)
        self.args=R.parser().parse_args([]);self.args.waves=False;self.args.timeout=30
        self.cases={c['id']:c for c in R.plans(self.args)}

    def test_arithmetic_and_all_fifo_clock_profiles(self):
        for name in ('arithmetic','fifo-fast','fifo-slow','fifo-phase','fifo-fractional','fifo-same-edge'):
            with self.subTest(name=name):
                result=R.simulate(self.args,self.cases[name],self.directory/name)
                self.assertTrue(result['success'],result)

    def test_stalls_tiny_prefill_and_busy_reset(self):
        for name in ('stream-small','stream-reset','display-tiny','display-reset'):
            with self.subTest(name=name):
                case=self.cases[name]
                if name=='display-reset':case['parameters'].update(W=17,H=9,D0=4,D1=8,D2=16)
                result=R.simulate(self.args,case,self.directory/name)
                self.assertTrue(result['success'],result)

    def test_safe_slow_supply_and_both_underflow_recoveries(self):
        for name in ('display-slow','display-clock-change','display-starve','display-clock-underflow'):
            with self.subTest(name=name):
                result=R.simulate(self.args,self.cases[name],self.directory/name)
                self.assertTrue(result['success'],result)

    def test_replay_reproduces_images_bubbles_stalls_and_occupancy(self):
        case=self.cases['stream-small']
        for name in ('first','again'):
            self.assertTrue(R.simulate(self.args,case,self.directory/name)['success'])
        for name in ('input.hex','pixels.csv','occupancy.csv'):
            self.assertEqual((self.directory/'first'/name).read_bytes(),(self.directory/'again'/name).read_bytes())
        result=R.C.compare(self.directory/'first',13,5,3,17,0,R.context(case))
        self.assertEqual(result['mismatches'],0)
        p=self.directory/'first/pixels.csv';text=p.read_text();p.write_text(text.replace(',000000,',',ffffff,',1) if ',000000,' in text else text.replace(',0\n',',1\n',1))
        with self.assertRaises(ValueError):R.C.compare(self.directory/'first',13,5,3,17,0,R.context(case))

    def test_arithmetic_mutation_and_fifo_gray_mutation_are_detected(self):
        for kind,file,old,new,label in (
            ('arithmetic','video_csc.sv','409*e','400*e','CHECK_FAIL ARITHMETIC'),
            ('fifo','video_async_fifo.sv','(next_wbin>>1)^next_wbin','next_wbin','LOCAL_WRITE_GRAY')):
            original=HERE/'rtl'/file;mutated=self.directory/file;mutated.write_text(original.read_text().replace(old,new))
            attr='ARITH_SOURCES' if kind=='arithmetic' else 'FIFO_SOURCES'
            sources=[mutated if p==original else p for p in getattr(R,attr)]
            case=self.cases['arithmetic' if kind=='arithmetic' else 'fifo-fast']
            with patch.object(R,attr,sources):result=R.simulate(self.args,case,self.directory/kind)
            self.assertFalse(result['success'])
            self.assertIn(label,(self.directory/kind/'simulation.log').read_text())

    def test_pipeline_failures_report_the_affected_pixel(self):
        for name,file,old,new,label,x in (
            ('drop-sof','video_key.sv','m_valid<=s_valid;','m_valid<=s_valid && s_data[55:32]!=KEY;','KEY_PACKET',0),
            ('corrupt-csc','video_csc.sv','convert(s_data[55:32]),',
             "(s_data[31:24]==8'd127 ? convert(s_data[55:32])^24'h000001:convert(s_data[55:32])),",'CSC_PACKET',2)):
            original=HERE/'rtl'/file;mutated=self.directory/file
            mutated.write_text(original.read_text().replace(old,new))
            with patch.object(R,'PIPELINE_SOURCES',[mutated if p==original else p for p in R.PIPELINE_SOURCES]):
                result=R.simulate(self.args,self.cases['stream-small'],self.directory/name)
            self.assertFalse(result['success'])
            log=(self.directory/name/'simulation.log').read_text()
            self.assertIn('CHECK_FAIL '+label,log)
            self.assertIn(f'frame=0 x={x} y=0',log)

    def test_unknown_fifo_payload_fails_in_four_state_simulation(self):
        original=HERE/'rtl/video_async_fifo.sv';mutated=self.directory/'video_async_fifo.sv'
        mutated.write_text(original.read_text().replace('memory[wbin[A-1:0]]<=wr_data;',"memory[wbin[A-1:0]]<='x;"))
        with patch.object(R,'FIFO_SOURCES',[mutated if p==original else p for p in R.FIFO_SOURCES]):
            result=R.simulate(self.args,self.cases['fifo-fast'],self.directory/'unknown')
        self.assertFalse(result['success'])
        log=(self.directory/'unknown/simulation.log').read_text()
        self.assertIn('CHECK_FAIL FIFO_3_ORDER',log)
        self.assertIn('actual=xxxxxxxx',log)


if __name__=='__main__':unittest.main()
