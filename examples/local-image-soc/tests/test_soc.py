import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('soc_test_support',HERE.parent/'local-image-sobel/support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
FW=S.load('soc_test_firmware',HERE/'firmware.py')


class FirmwareTests(unittest.TestCase):
    def test_reset_jump_and_interrupt_handler_have_known_encodings(self):
        binary=FW.program([[12]*25],[[0]*25])
        self.assertEqual(binary[:5],[0x0140006f,0x00462e03,0x000e0f93,0x01c62223,0x30200073])

    def test_all_scenarios_fit_rom_and_success_cases_compare_every_pixel(self):
        frames=S.MODEL.random_frames(7,5,17,2);gold=[S.MODEL.sobel(f,7,5) for f in frames]
        for scenario in range(7):
            binary=FW.program(frames,gold,scenario)
            self.assertLessEqual(len(binary),1024)
            reads=sum((word&0x707f)==0x2003 and ((word>>15)&31)==11 for word in binary)
            self.assertEqual(reads,0 if scenario in (1,2) else 70)

    def test_invalid_program_inputs_are_rejected(self):
        for frames,expected,scenario in (([],[],0),([[0]],[],0),([[0]],[[0,1]],0),([[256]],[[0]],0),([[0]],[[0]],7)):
            with self.subTest(frames=frames,scenario=scenario),self.assertRaises(ValueError):FW.program(frames,expected,scenario)

    def test_oversized_rom_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'ROM capacity'):FW.program([[0]*256]*3,[[0]*256]*3)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
        (self.d/'ram-readback.hex').write_text('a5a50000\na5a50001\n')
        (self.d/'retirement.log').write_text('00000000 0140006f 0 0 00000000 00000000 00000000\n')
        self.counts=dict(pixels=2,frames=1,cpu_checks=2,irqs=1,resets=0)

    def test_readback_and_cpu_checks_are_required(self):
        S.validate_completion(self.d,[[0,1]],self.counts,0,True)
        with self.assertRaises(ValueError):S.validate_completion(self.d,[[0,1]],dict(self.counts,cpu_checks=0),0,True)

    def test_upper_bytes_and_missing_pixels_are_rejected(self):
        for data in ('00000000\n00000001\n','a5a50000\n','a5a50000\na5a50002\n'):
            (self.d/'ram-readback.hex').write_text(data)
            with self.subTest(data=data),self.assertRaisesRegex(ValueError,'RAM readback'):S.validate_completion(self.d,[[0,1]],self.counts,0,True)

    def test_empty_retirement_trace_is_rejected(self):
        (self.d/'retirement.log').write_text('')
        with self.assertRaisesRegex(ValueError,'retirement'):S.validate_completion(self.d,[[0,1]],self.counts,0,True)

    def test_error_interrupt_and_reset_cases_have_distinct_counts(self):
        for scenario,counts in ((1,dict(self.counts,cpu_checks=0)),(3,dict(self.counts,irqs=4)),(5,dict(self.counts,resets=1))):
            S.validate_completion(self.d,[[0,1]],counts,scenario,True)
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):S.validate_completion(self.d,[[0,1]],self.counts,scenario,True)


if __name__=='__main__':unittest.main()
