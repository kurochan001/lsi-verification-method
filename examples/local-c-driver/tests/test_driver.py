from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,read_json
P=load_example('local-c-driver')
class DriverTest(unittest.TestCase):
    def test_plan_counts_include_timeout_recovery_start(self):
        self.assertEqual(P.totals(P.operations(17,0,True)),dict(starts=9,copies=6,errors=2,timeouts=1))
    @unittest.skipUnless(shutil.which('cc'),'C compiler required')
    def test_c_api_without_rtl(self):
        body='''#include "dma_driver.h"
#include <assert.h>
static unsigned address[8],data[8],n,status;
static int rd(void*u,uint32_t a,uint32_t*v){(void)u;(void)a;*v=status;return 0;}
static int wr(void*u,uint32_t a,uint32_t v){(void)u;address[n]=a;data[n++]=v;return 0;}
static void idle(void*u){(void)u;}
int main(void){dma_device d={0,rd,wr,idle,0};assert(dma_submit(&d,4,256,8)==0);assert(n==4&&address[2]==8&&data[2]==8);status=0;assert(dma_wait(&d,0)==DMA_TIMEOUT);status=6;assert(dma_wait(&d,1)==DMA_HW_ERROR);status=10;assert(dma_wait(&d,1)==DMA_ABORTED);status=18;n=0;assert(dma_ack_irq(&d)==1&&address[0]==12&&data[0]==4);return 0;}'''
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'test.c';src.write_text(body);binary=Path(tmp)/'test'
            p=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(P.HERE/'c'),str(src),str(P.HERE/'c/dma_driver.c'),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(subprocess.run([str(binary)]).returncode,0)
    @unittest.skipUnless(shutil.which('verilator') and shutil.which('cc'),'native tools required')
    def test_real_c_driver_and_four_software_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=subprocess.run([sys.executable,P.__file__,'--iterations','2','--out',str(out)],capture_output=True,text=True,timeout=90)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);summary=read_json(out/'summary.json');self.assertTrue(summary['success'])
            self.assertEqual(sum(r['outcome']=='detected' for r in summary['results']),4)
            self.assertIn('-std=c11',read_json(out/'build/c-build.json')['command'])
            self.assertEqual(read_json(out/'coverage.json')['host-c']['hit'],8)
    def test_seed_reproduction(self):
        self.assertEqual(P.operations(17,8),P.operations(17,8));self.assertNotEqual(P.operations(17,8),P.operations(18,8))
if __name__=='__main__':unittest.main()
