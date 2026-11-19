"""Real frame ownership plus independent pixel, timing, X and truncation checks."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
HERE=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('frames_test',HERE/'run.py')
R=importlib.util.module_from_spec(s);s.loader.exec_module(R)


class FrameTests(unittest.TestCase):
    def test_images_are_seeded_and_first_pixel_is_hand_checkable(self):
        self.assertEqual(R.M.image(1,1,65,17)[0][2],(65*71)%256)
        self.assertEqual(R.M.vectors(8,4,17),R.M.vectors(8,4,17))
        self.assertNotEqual(R.M.vectors(8,4,17),R.M.vectors(8,4,18))
        rows=R.M.vectors(7,3,17)
        self.assertEqual(sum(r[1] for r in rows),4)
        self.assertEqual(sum(r[2] for r in rows),12)

    def test_all_real_clocks_sizes_and_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            for case in R.cases(SimpleNamespace(seed=17,profile='smoke')):
                result=sim.execute(case)
                self.assertEqual(result['status'],'detected' if case.get('expected_failure') else 'pass',result)
                if not case.get('expected_failure'):
                    self.assertTrue(R.GOALS<=set(result['goals']))
                    self.assertTrue((Path(tmp)/case['id']/'actual-65.ppm').is_file())

    def test_pixel_timing_unknown_and_truncation_are_not_ignored(self):
        case=R.cases(SimpleNamespace(seed=17,profile='smoke'))[0]
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            self.assertEqual(sim.execute(case)['status'],'pass')
            directory=Path(tmp)/case['id'];path=directory/'trace.csv';original=path.read_text()
            rows=original.splitlines();index=next(i for i,line in enumerate(rows[1:],1) if line.endswith(',1'))
            for column,value in ((2,'xxxxxx'),(2,'ffffff'),(3,'0'),(1,'1')):
                changed=rows[:];fields=changed[index].split(',');fields[column]=value;changed[index]=','.join(fields)
                path.write_text('\n'.join(changed)+'\n')
                self.assertFalse(R.M.compare(case,directory)['success'])
            path.write_text('\n'.join(rows[:-1])+'\n')
            with self.assertRaisesRegex(ValueError,'truncated'):R.M.compare(case,directory)

    def test_ppm_contains_exact_binary_rgb_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.ppm';R.M.ppm(path,2,1,[(0,127,255),(1,128,254)])
            self.assertEqual(path.read_bytes(),b'P6\n2 1\n255\n\x00\x7f\xff\x01\x80\xfe')

    def test_malformed_sof_and_eol_are_reported_by_the_real_dut(self):
        base=R.cases(SimpleNamespace(seed=17,profile='smoke'))[0]
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            for column,value in ((1,'0'),(2,'1')):
                lines=base['text'].splitlines();fields=lines[0].split();fields[column]=value;lines[0]=' '.join(fields)
                case=dict(base,id=f'bad-marker-{column}',text='\n'.join(lines)+'\n',expected_failure=R.LABEL)
                result=sim.execute(case);self.assertEqual(result['status'],'detected',result)
                self.assertIn('packet protocol error',(Path(tmp)/case['id']/'simulation.log').read_text())


if __name__=='__main__':unittest.main()
