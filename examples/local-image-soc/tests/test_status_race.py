"""A W1C on the completion edge must not lose done or error, which firmware cannot place exactly."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
SOURCES=[HERE.parent/'local-conv-window/rtl/conv_window.sv',HERE.parent/'local-image-sobel/rtl/sobel_stream.sv',HERE/'rtl/image_dma.sv',HERE/'tb/dma_status_tb.sv']
COMPLETION='done<=!error_seen && bresp==0 && bid==0 && received==N;'
W1C_AFTER=COMPLETION+'if(psel && penable && pwrite && paddr==4)begin if(pwdata[1])done<=0;if(pwdata[2])error<=0;end'


def simulate(bresp,edit=None):
    if not (shutil.which('iverilog') and shutil.which('vvp')):raise unittest.SkipTest('Icarus required')
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);files=[]
        for source in SOURCES:
            if edit and source.name=='image_dma.sv':
                text=source.read_text()
                if edit[0] not in text:raise ValueError(f'Edit target missing: {edit[0]}')
                source=out/source.name;source.write_text(text.replace(*edit))
            files.append(str(source))
        subprocess.run(['iverilog','-g2012','-s','dma_status_tb','-o',str(out/'sim.vvp'),*files],check=True,capture_output=True,text=True,timeout=30)
        return subprocess.run(['vvp',str(out/'sim.vvp'),f'+BRESP={bresp}'],capture_output=True,text=True,timeout=60)


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


if __name__=='__main__':unittest.main()
