"""A W1C on the completion edge must not lose done or error, which firmware cannot place exactly."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
SOURCES=[HERE.parent/'local-conv-window/rtl/conv_window.sv',HERE.parent/'local-image-sobel/rtl/sobel_stream.sv',HERE/'rtl/image_dma.sv',HERE/'tb/dma_status_tb.sv']
COMPLETION='done<=!error_seen && bresp==0 && bid==0 && received==N;'
FAILURE='error<=error_seen || bresp!=0 || bid!=0 || received!=N;'
MIDDLE='else if(bresp!=0 || bid!=0)error_seen<=1;'
# Weakened completion logic that drops one error condition at a time.
NO_LAST_BID=(((FAILURE,'error<=error_seen || bresp!=0 || received!=N;'),(COMPLETION,'done<=!error_seen && bresp==0 && received==N;')),'+BID_AT=99')
NO_MIDDLE_BID=((MIDDLE,'else if(bresp!=0)error_seen<=1;'),'+BID_AT=2')
NO_COUNT=(((FAILURE,'error<=error_seen || bresp!=0 || bid!=0;'),(COMPLETION,'done<=!error_seen && bresp==0 && bid==0;')),'+EXTRA_R=1')
W1C_AFTER=COMPLETION+'if(psel && penable && pwrite && paddr==4)begin if(pwdata[1])done<=0;if(pwdata[2])error<=0;end'


def simulate(bresp,edit=None,*extra):
    if not (shutil.which('iverilog') and shutil.which('vvp')):raise unittest.SkipTest('Icarus required')
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);files=[]
        for source in SOURCES:
            if edit and source.name=='image_dma.sv':
                text=source.read_text()
                for old,new in ([edit] if isinstance(edit[0],str) else edit):
                    if old not in text:raise ValueError(f'Edit target missing: {old}')
                    text=text.replace(old,new)
                source=out/source.name;source.write_text(text)
            files.append(str(source))
        subprocess.run(['iverilog','-g2012','-s','dma_status_tb','-o',str(out/'sim.vvp'),*files],check=True,capture_output=True,text=True,timeout=30)
        return subprocess.run(['vvp',str(out/'sim.vvp'),f'+BRESP={bresp}',*extra],capture_output=True,text=True,timeout=60)


class StatusRaceTests(unittest.TestCase):
    def test_the_completion_wins_over_a_w1c_on_the_same_edge(self):
        for bresp in (0,2):
            with self.subTest(bresp=bresp):
                result=simulate(bresp);self.assertEqual(result.returncode,0,result.stdout);self.assertIn('RESULT PASS',result.stdout)

    def test_a_w1c_that_wins_over_the_completion_is_detected(self):
        for bresp in (0,2):
            with self.subTest(bresp=bresp):
                result=simulate(bresp,(COMPLETION,W1C_AFTER))
                self.assertNotEqual(result.returncode,0);self.assertIn('CHECK_FAIL DMA_STATUS_LOST',result.stdout)


    def test_a_wrong_b_id_or_an_extra_read_beat_alone_ends_in_error(self):
        for argument in ('+BID_AT=99','+BID_AT=2','+EXTRA_R=1'):
            with self.subTest(argument=argument):
                result=simulate(0,None,argument);self.assertEqual(result.returncode,0,result.stdout);self.assertIn('RESULT PASS',result.stdout)

    def test_dropping_one_error_condition_is_detected(self):
        for edit,argument in (NO_LAST_BID,NO_MIDDLE_BID,NO_COUNT):
            with self.subTest(argument=argument):
                result=simulate(0,edit,argument)
                self.assertNotEqual(result.returncode,0);self.assertIn('CHECK_FAIL DMA_STATUS_LOST',result.stdout)
                # The same weakened logic still passes the tests that existed before, which is the gap.
                self.assertEqual(simulate(2,edit).returncode,0)


if __name__=='__main__':unittest.main()
