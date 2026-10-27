from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,read_json
V=load_example('local-bus-validation')


class ValidationTest(unittest.TestCase):
    def test_cross_denominators_are_explicit(self):
        self.assertEqual(len(V.cross_plan('ahb')),12)
        self.assertEqual(len(V.cross_plan('axi')),22)
        self.assertIn('axi/order1/strobe0/stall1',V.cross_plan('axi'))

    def test_stress_contains_expected_completions_in_every_configuration(self):
        args=SimpleNamespace(transfers=8,seed=17,profile='smoke')
        for bus,plugin in [('ahb',V.AHB),('axi',V.AXI)]:
            for parameters in plugin.CONFIGS.values():
                c=next(c for c in V.cases(bus,parameters,args) if c['id']=='throughput')
                expected=sum(c['counts'][k] for k in ('reads','writes','errors')) if bus=='ahb' else c['counts']['b']+c['counts']['r']
                self.assertEqual(expected,16)

    def test_performance_checks_counts_latency_spacing_and_total(self):
        case=dict(id='throughput',counts=dict(reads=2,writes=2,errors=0))
        log=''.join(f'PERF ahb latency=2 cycle={clock}\n' for clock in (2,4,6,8))+'PERF_TOTAL ahb first=0 last=8 completed=4\n'
        result=V.performance(log,'ahb',dict(WAIT_CYCLES=1),case,2)
        self.assertEqual(result['steady_completions_per_cycle'],0.5)
        for damaged in (log.replace('cycle=6','cycle=7'),log.replace('latency=2','latency=3'),
                        log.replace('completed=4','completed=5'),log+log.splitlines()[-1]+'\n',
                        log.replace('PERF ahb latency=2 cycle=4\n','')):
            with self.subTest(damaged=damaged),self.assertRaises(ValueError):
                V.performance(damaged,'ahb',dict(WAIT_CYCLES=1),case,2)

    def test_native_database_requires_fixed_inventory_and_both_code_kinds(self):
        checker=V.CHECKERS[0];rtl=V.AHB.SOURCES[0]
        def record(path,page,label):
            metadata={'f':str(path),'page':page,'o':label}
            fields=''.join('\x01'+key+'\x02'+value for key,value in metadata.items())
            return "C '"+fields+"' 1\n"
        records=[record(checker,'v_user/checker',name) for name in ('cp_address_wait','cp_error','cp_pipeline')]
        records += [record(rtl,'v_line/dut','line'),record(rtl,'v_toggle/dut','toggle')]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'coverage.dat';path.write_text(''.join(records))
            self.assertEqual(len(V.native(path,checker,'ahb',rtl)['user']),3)
            for malformed in (''.join(records[:-1]),''.join(records[1:]),''.join(records+[records[0]]),'not coverage\n'):
                path.write_text(malformed)
                with self.subTest(malformed=malformed),self.assertRaises(ValueError):V.native(path,checker,'ahb',rtl)

    def test_invalid_count_and_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            p=subprocess.run([sys.executable,V.__file__,'--transfers','0','--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertFalse(out.exists())
            out.mkdir();(out/'keep').write_text('keep')
            p=subprocess.run([sys.executable,V.__file__,'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertEqual((out/'keep').read_text(),'keep')

    @unittest.skipUnless(all(shutil.which(n) for n in ('verilator','iverilog','vvp')),'simulation tools required')
    def test_independent_checkers_x_and_between_edges_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            p=subprocess.run([sys.executable,V.__file__,'--stage','fixtures','--out',str(out)],capture_output=True,text=True,timeout=90)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            summary=read_json(out/'summary.json');self.assertTrue(summary['success'])
            results={r['id']:r for r in summary['results']}
            self.assertEqual(len(results),33)
            for backend in ('sva','four-state'):
                for bus,scenario in (('ahb',6),('axi',9)):
                    self.assertEqual(results[f'{backend}-{bus}-scenario{scenario}']['status'],'pass')
            for name in ('four-state-ahb-scenario4','four-state-axi-scenario7'):
                self.assertEqual(results[name]['status'],'detected')
            self.assertEqual(results['actual-async-reset']['status'],'pass')

if __name__=='__main__':unittest.main()
