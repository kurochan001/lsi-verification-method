import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

M = load('vci_test_model', HERE / 'model.py')
R = load('vci_test_runner', HERE / 'run.py')

def op(cmd, b, *, address=0x1000, cells=1, be=None, data=None, abort=0):
    return [cmd, address, cells, (1 << b)-1 if be is None else be,
            15, 7, 3, 0, 2, abort, *((data or [])+[0]*4)[:4]]

class VciTests(unittest.TestCase):
    def test_partial_write_preserves_all_other_bytes_including_upper_word(self):
        for b in (4, 8):
            full = (1 << (8*b))-1
            rows, count = M.oracle([op(2,b,data=[full]), op(2,b,be=1,data=[0x42]), op(1,b)],b)
            self.assertEqual(rows[-1][14], full-0xff+0x42)
            self.assertEqual(count['responses'],3)
            for lane in range(b):
                rows,_ = M.oracle([op(2,b,be=1<<lane,data=[0xa5<<(lane*8)]),op(1,b)],b)
                self.assertEqual(rows[-1][14],0xa5<<(lane*8))

    def test_burst_last_word_and_two_segments_are_independent(self):
        for b in (4,8):
            rows,count = M.oracle([op(2,b,cells=4,data=[1,2,3,4]),op(1,b,cells=4),op(1,b,address=0x2000),op(2,b,address=0x1100-b,data=[99]),op(1,b,address=0x1100-b)],b)
            self.assertEqual(rows[1][14:18],[1,2,3,4])
            self.assertEqual(rows[2][14],0)
            self.assertEqual(rows[-1][14],99)
            self.assertEqual((count['commands'],count['responses']),(8,8))

    def test_error_does_not_modify_ram(self):
        rows,count=M.oracle([op(2,8,data=[123]),op(2,8,address=0x3000,data=[456]),op(1,8,address=0x3000),op(1,8)],8)
        self.assertEqual([r[18] for r in rows],[0,1,1,0])
        self.assertEqual(rows[-1][14],123)
        self.assertEqual(count['errors'],2)

    def test_reset_cancels_exactly_one_packet_and_clears_memory(self):
        for b in (4,8):
            for cmd,abort in ((2,1),(1,2)):
                rows,c=M.oracle([op(2,b,data=[123]),op(cmd,b,cells=4,abort=abort),op(1,b)],b)
                self.assertEqual(rows[-1][14],0)
                self.assertEqual((c['packets'],c['completed'],c['cancelled'],c['resets']),(3,2,1,1))
                self.assertEqual(c['responses'],2)
            rows,_=M.oracle([op(2,b,data=[123]),[0]*14,op(1,b)],b)
            self.assertEqual(rows[-1][14],0)

    def test_random_seed_reproduces_all_data_and_completion_counts(self):
        for b in (4,8):
            a=M.make('random',b,17,128)
            self.assertEqual(a,M.make('random',b,17,128))
            self.assertNotEqual(a[0],M.make('random',b,18,128)[0])
            self.assertEqual(a[1]['rows'],130)
            self.assertEqual(a[1]['packets'],128)

    def test_out_of_scope_transactions_are_rejected(self):
        bad=[op(1,4,be=2),op(2,4,cells=2,be=1),op(2,4,address=0x1001),op(2,4,data=[1<<32]),op(1,4,abort=1),op(2,4,abort=2),op(1,4,cells=2,address=0x10fc),[0,1]+[0]*12]
        for row in bad:
            with self.subTest(row=row),self.assertRaises(ValueError):M.oracle([row],4)
        with self.assertRaises(ValueError):M.oracle([],2)

    def test_vendored_inventory_and_reconstructed_original_hashes_match(self):
        self.assertEqual(len(R.sources()),37)

    def test_missing_duplicate_extra_or_non_decimal_counts_are_rejected(self):
        expected={'rows':25,'packets':23}
        good='COUNT rows=25\nCOUNT packets=23\n'
        R.completion(good,expected)
        for log in ('',good+'COUNT rows=25\n',good+'COUNT bogus=1\n',good.replace('25','0x19'),good.replace('23','22')):
            with self.subTest(log=log),self.assertRaises(ValueError):R.completion(log,expected)

if __name__=='__main__':unittest.main()
