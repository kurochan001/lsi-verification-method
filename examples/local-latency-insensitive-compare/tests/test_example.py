import importlib.util
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('li_run',HERE/'run.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
TOOLS=('verilator','c++','make')

class ModelAndCompareTests(unittest.TestCase):
    """The C++ model and the stream comparison, built on their own with the host compiler."""
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name);cls.binary=root/'driver';source=root/'driver.cpp'
        source.write_text('''#include "dot_model.hpp"
#include "stream_compare.hpp"
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
static std::vector<std::int64_t> parse_list(const std::string& s) {
    std::vector<std::int64_t> out;
    std::istringstream in(s == "," ? "" : s);
    std::string x;
    while (std::getline(in, x, ',')) {
        if (!x.empty()) out.push_back(std::stoll(x));
    }
    return out;
}
int main() {
    std::string line;
    DotModel m;
    while (std::getline(std::cin, line)) {
        std::istringstream w(line);
        std::string k;
        w >> k;
        if (k == "M") {
            DotTxn t;
            for (auto& v : t.a) w >> v;
            for (auto& v : t.b) w >> v;
            try {
                std::cout << m.accept(t) << "\\n";
            } catch (const std::exception&) {
                std::cout << "REJECT\\n";
            }
        } else if (k == "C") {
            int p;
            std::string expected, actual;
            w >> p >> expected >> actual;
            auto r = classify_stream(parse_list(expected), parse_list(actual), p == 1);
            std::cout << (r.empty() ? "OK" : r) << "\\n";
        }
    }
    return 0;
}
''')
        # GCC and clang warn about different things; show the compiler's message when -Werror stops the build.
        built=subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(HERE/'model'),str(source),str(HERE/'model/dot_model.cpp'),'-o',str(cls.binary)],capture_output=True,text=True)
        if built.returncode:raise AssertionError('the test driver does not compile:\n'+built.stderr)

    def ask(self,lines):
        r=subprocess.run([str(self.binary)],input='\n'.join(lines)+'\n',text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);return r.stdout.split()

    def test_model_agrees_with_a_python_dot_product(self):
        rng=random.Random(5);cases=[[-128]*8,[-128]*4+[127]*4,[127]*8,[0]*8,[1,-1,2,-2,1,1,1,1]]+[[rng.randrange(-128,128) for _ in range(8)] for _ in range(2000)]
        got=self.ask(['M '+' '.join(map(str,c)) for c in cases])
        self.assertEqual(got,[str(sum(c[i]*c[4+i] for i in range(4))) for c in cases])
        self.assertEqual(got[:3],['65536','-65024','64516'])

    def test_model_rejects_operands_outside_signed_8_bits(self):
        self.assertEqual(self.ask(['M 128 0 0 0 0 0 0 0','M 0 0 0 0 0 0 0 -129','M 0 0 0 0 1 1 1 1']),['REJECT','REJECT','0'])

    def test_stream_comparison_names_each_kind_of_difference(self):
        table=[(0,'1,2,3','1,2,3','OK'),(0,'1,2,3','1,3,2','LI_ORDER'),(0,'1,2,3','1,1,2,3','LI_DUP'),(0,'1,2,3','1,3','LI_DROP'),
               (0,'1,2,3','9,1,2,3','LI_EXTRA'),(0,'1,2,3','1,2,4','LI_DATA'),(0,'1,2,3','1,2','LI_DROP'),
               (1,'1,2,3','1,2','OK'),(1,'1,2,3',',','OK'),(1,'1,2,3','2,3','LI_DROP'),(1,'1,2','1,2,2','LI_DUP'),(0,'1,2',',','LI_DROP')]
        self.assertEqual(self.ask([f'C {p} {e} {a}' for p,e,a,_ in table]),[x for *_,x in table])

class PlanTests(unittest.TestCase):
    def args(self,**k):return SimpleNamespace(**{**dict(configuration='all',seed=17,profile='smoke'),**k})

    def test_plan_size_and_the_scope_of_partial_runs(self):
        self.assertEqual(len(R.plan_of(self.args())[2]),27)
        self.assertEqual(len(R.plan_of(self.args(profile='nightly'))[2]),33)
        partial=R.plan_of(self.args(configuration='pipe-split'))[2]
        self.assertEqual(partial,['toolchain','pipe-split/flow','pipe-split/reset','pipe-split/random-17','pipe-split/coverage','source-freshness'])
        self.assertNotIn('diagnose-cycle-compare',R.plan_of(self.args(configuration='pipe'))[2])
        self.assertIn('diagnose-weak-check',R.plan_of(self.args(configuration='pipe'))[2])

    def test_expected_counts_leave_out_what_a_reset_cancels(self):
        self.assertEqual(R.expectations(R.flow_steps()),(38,0))
        self.assertEqual(R.expectations(R.reset_steps()),(9,2))
        self.assertEqual(R.expectations(R.random_steps(17,40)),(40,0))
        with self.assertRaises(ValueError):R.expectations(['FILL 2','T 0 0 0 0 0 0 0 0'])

    def test_fixed_lists_hold_the_boundaries_and_every_operand_is_signed_8_bit(self):
        flow=R.flow_steps()
        for row in ('T '+' '.join(['-128']*8),'T '+' '.join(['-128']*4+['127']*4),'T 1 -1 2 -2 1 1 1 1','T 0 0 0 -5 0 0 0 7'):self.assertIn(row,flow)
        for m in ('MODE burst','MODE alt','MODE on'):self.assertIn(m,flow)
        reset=R.reset_steps();self.assertIn('RESETAFTER 1',reset);self.assertIn('FILL 6',reset)
        for steps in (flow,reset,R.random_steps(3,120)):
            for s in steps:
                if s.startswith('T '):
                    values=list(map(int,s.split()[1:]));self.assertEqual(len(values),8);self.assertTrue(all(-128<=v<128 for v in values))

    def test_mutants_have_distinct_owners_and_the_blind_ones_are_protocol_errors(self):
        self.assertEqual({m:v[2] for m,v in R.MUTANTS.items()},{1:'LI_ORDER',2:'LI_DUP',3:'LI_DROP',4:'LI_WITHDRAW',5:'LI_EXTRA',6:'LI_DATA',7:'LI_HOLD',8:'LI_DROP',9:'LI_DATA'})
        self.assertEqual({R.MUTANTS[m][2] for m in R.BLIND},{'LI_WITHDRAW','LI_HOLD'})
        self.assertTrue(all(v[0] in R.CONFIGS and v[1] in ('flow','reset') for v in R.MUTANTS.values()))

    def test_goals_depend_on_the_implementation(self):
        catalog=json.loads(R.REQUIREMENTS.read_text())
        seq,pipe=R.required(catalog,'seq'),R.required(catalog,'pipe')
        self.assertEqual((len(seq),len(pipe)),(14,16))
        self.assertIn('seq/accept-on-delivery',seq);self.assertNotIn('pipe/full',seq)
        self.assertIn('pipe/full',pipe);self.assertNotIn('seq/accept-on-delivery',pipe)
        self.assertEqual(pipe,R.required(catalog,'pipe-split'))

    def test_cycle_and_weak_checks(self):
        a=[(5,70),(6,1)];b=[(7,70),(9,1)]
        self.assertEqual(R.cycle_compare(a,b)['index'],0);self.assertIsNone(R.cycle_compare(a,list(a)))
        self.assertEqual(R.cycle_compare(a,a[:1])['index'],1)
        self.assertTrue(R.weak_check([1,2,3],[3,2,1]));self.assertFalse(R.weak_check([1,2,3],[1,2]));self.assertFalse(R.weak_check([1,2,3],[1,2,4]))

class RealRun(unittest.TestCase):
    def test_one_configuration_passes_and_a_missing_tool_fails(self):
        self.assertEqual([t for t in TOOLS if not shutil.which(t)],[])
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            r=subprocess.run([sys.executable,str(HERE/'run.py'),'--configuration','pipe-split','--out',str(out)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout[-2000:]+r.stderr[-2000:])
            summary=json.loads((out/'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete']);self.assertEqual(summary['planned'],6)
            self.assertEqual((out/'junit.xml').read_text().count('<testcase'),6)
            log=(out/'pipe-split/reset/simulation.log').read_text()
            self.assertIn('COUNT resets=2',log);self.assertIn('cancelled=6',log)
            self.assertEqual(R.read_transfers(out/'pipe-split/flow/transfers.csv')[0],(6,70))
            broken=subprocess.run([sys.executable,str(HERE/'run.py'),'--configuration','pipe-split','--verilator','no-such-verilator','--out',str(Path(tmp)/'broken')],capture_output=True,text=True)
            self.assertEqual(broken.returncode,1)

if __name__=='__main__':unittest.main()
