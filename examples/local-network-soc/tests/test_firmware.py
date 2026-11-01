import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('nic_fw_tests',HERE/'firmware.py');F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)


class FirmwareTests(unittest.TestCase):
    def test_known_reset_and_interrupt_encodings(self):
        self.assertEqual(F.program([])[:5],[0x0140006f,0x00462e03,0x01cfefb3,0x01c62223,0x30200073])
    def test_golden_table_is_data_after_code(self):
        replies=[bytes(range(64)),bytes(range(128))];b=F.program(replies)
        self.assertEqual(b[512:],[64,*replies[0],128,*replies[1]]);self.assertLessEqual(len(b),1024)
    def test_all_error_programs_and_supported_sizes_fit_rom(self):
        for size in (96,128):
            for scenario in (0,1,2,3):self.assertLessEqual(len(F.program([bytes(size)]*3,size,2,scenario)),1024)
    def test_oversized_tables_do_not_overwrite_rom(self):
        with self.assertRaisesRegex(ValueError,'ROM table'):F.program([bytes(128)]*4)
    def test_invalid_contracts_are_rejected(self):
        for replies,size,drops,scenario in (([bytes(63)],128,0,0),([bytes(97)],96,0,0),([],129,0,0),([],128,0,4),([],128,-1,0),([[256]*64],128,0,0)):
            with self.subTest(size=size,scenario=scenario),self.assertRaises(ValueError):F.program(replies,size,drops,scenario)
    def test_immediates_preserve_high_bits_and_signed_low_bits(self):
        for value in (0,0x800,0x1000,0xedb88320,0x600d600d,0xbad0bad0,0xffffffff):
            ops=F.li(1,value);self.assertEqual(((ops[0][2]<<12)+ops[1][3])&0xffffffff,value)
if __name__=='__main__':unittest.main()
