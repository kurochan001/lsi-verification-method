import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('cosim_test_runner',HERE/'run.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)

class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);root=Path(cls.temp.name);cls.binary=root/'model'
        source=root/'test.cpp';source.write_text('''#include "model.hpp"
#include <cassert>
#include <limits>
int main(){
 assert(std::abs(rc_advance(0,1,1e-4,1000,1e-7)-(1-std::exp(-1.0)))<1e-14);
 assert(rc_advance(.7,1,0,1000,1e-7)==.7);
 auto x=rc_advance(.8,0,2e-4,1000,1e-7);assert(x>0 && x<.8);
 auto half=rc_advance(0,1,5e-5,1000,1e-7);assert(std::abs(rc_advance(half,1,5e-5,1000,1e-7)-rc_advance(0,1,1e-4,1000,1e-7))<1e-14);
 assert(reference_adc(-1,8)==0 && reference_adc(3.3,8)==255 && reference_adc(5,10)==1023 && reference_adc(1.65,8)==128);
 assert(next_drive(false,true,true,3,10,20));assert(!next_drive(true,true,true,30,10,20));
 assert(next_drive(true,true,true,15,10,20));assert(!next_drive(false,true,true,15,10,20));
 assert(!next_drive(true,false,true,0,10,20));assert(!next_drive(true,true,false,0,10,20));
 try{rc_advance(0,1,-1,1000,1e-7);return 1;}catch(const std::invalid_argument&){}
 try{reference_adc(std::numeric_limits<double>::quiet_NaN(),8);return 1;}catch(const std::invalid_argument&){}
}
''')
        subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(HERE),str(source),'-o',str(cls.binary)],check=True,capture_output=True)

    def test_rc_solution_composition_quantization_and_hysteresis_contract(self):
        subprocess.run([str(self.binary)],check=True,capture_output=True)

    def test_seed_and_expected_program_counts_are_reproducible(self):
        for bits in (8,10):
            rows=R.program('random',bits,17,640)
            self.assertEqual(rows,R.program('random',bits,17,640))
            self.assertNotEqual(rows,R.program('random',bits,18,640))
            self.assertEqual(len(rows),640)
            self.assertTrue(all(r[2]<r[3]<(1<<bits) for r in rows))
            reset=R.program('reset-enable',bits,17,1)
            self.assertEqual(sum(not r[0] for r in reset),3)
            self.assertEqual(sum(not r[1] for r in reset),30)

    def test_actual_shared_api_initialization_isolated_config_and_rc_solution(self):
        config=shutil.which('lsi-ngspice-config')
        self.assertIsNotNone(config,'prepare ngspice and add install/bin to PATH for all selftests')
        prefix=subprocess.check_output([config,'--prefix'],text=True).strip()
        code='import json,sys;sys.path.insert(0,sys.argv[1]);import ngspice;print(json.dumps(ngspice.probe(sys.argv[2])))'
        result=subprocess.run([sys.executable,'-c',code,str(ROOT/'tools'),prefix],check=True,capture_output=True,text=True)
        probe=json.loads(result.stdout)
        self.assertTrue(probe['success']);self.assertTrue(probe['user_init_ignored']);self.assertEqual(probe['release'],'47')
        self.assertLess(probe['error'],1e-4);self.assertGreater(probe['points'],500)

if __name__=='__main__':unittest.main()
