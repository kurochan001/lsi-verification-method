import math
from fractions import Fraction
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]

class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name);cls.binary=root/'reference'
        source=root/'test.cpp'
        source.write_text('''#include "reference.hpp"
#include <iostream>
#include <string>
int main(int argc,char** argv){try{if(argc!=2)return 2;FirReference m(std::stoul(argv[1]));std::string s;while(std::cin>>s){if(s=="R"){m.reset();continue;}auto r=m.accept(std::stoi(s));std::cout<<r.value<<","<<r.sum<<","<<r.clip_high<<","<<r.clip_low<<"\\n";}return 0;}catch(...){return 2;}}
''')
        subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(HERE/'model'),str(source),str(HERE/'model/reference.cpp'),'-o',str(cls.binary)],check=True,capture_output=True)

    def execute(self,width,values):
        return subprocess.run([str(self.binary),str(width)],input='\n'.join(map(str,values))+'\n',text=True,capture_output=True)

    def test_model_agrees_with_exact_rational_math_and_reset_for_both_widths(self):
        for width in (8,12):
            limit=1<<(width-1);rng=random.Random(100+width)
            values=[0,1,0,0,-1,0,0,limit-1,-limit,limit-1,-limit]+[rng.randrange(-limit,limit) for _ in range(1000)]
            program=[];expected=[];past=[0,0]
            for i,value in enumerate(values):
                if i%97==0:program.append('R');past=[0,0]
                program.append(value);s=3*value-2*past[0]+past[1]
                exact=Fraction(s,4)
                rounded=math.floor(exact+Fraction(1,2)) if s>=0 else math.ceil(exact-Fraction(1,2))
                expected.append([min(limit-1,max(-limit,rounded)),s,int(rounded>=limit),int(rounded < -limit)])
                past=[value,past[0]]
            result=self.execute(width,program);self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual([list(map(int,line.split(','))) for line in result.stdout.splitlines()],expected)

    def test_ties_round_away_from_zero(self):
        r=self.execute(8,[1,0,'R',-1,0])
        self.assertEqual([line.split(',')[0] for line in r.stdout.splitlines()],['1','-1','-1','1'])

    def test_rounded_values_next_to_the_limits_are_saturated_exactly(self):
        for width in (8,12):
            limit=1<<(width-1);half=limit//2;hi=limit-1;lo=-limit
            for values,expected,clip in (([1,-half-1,hi],hi,'1,0'),([-3,-half-1,hi],hi,'0,0'),([0,half+2,lo],lo,'0,1'),([0,half,lo],lo,'0,0')):
                lines=self.execute(width,values).stdout.splitlines()
                with self.subTest(width=width,values=values):
                    self.assertEqual(int(lines[-1].split(',')[0]),expected);self.assertEqual(lines[-1].split(',',2)[2],clip)

    def test_invalid_width_and_out_of_range_inputs_fail(self):
        for width,values in [(4,[0]),(8,[128]),(8,[-129]),(12,[2048]),(12,[-2049])]:
            with self.subTest(width=width,values=values):self.assertNotEqual(self.execute(width,values).returncode,0)

if __name__=='__main__':unittest.main()
