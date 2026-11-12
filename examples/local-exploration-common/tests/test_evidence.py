import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
PATH=Path(__file__).resolve().parents[1]/'evidence.py'
spec=importlib.util.spec_from_file_location('search_support',PATH);P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
class PlannedEvidenceTests(unittest.TestCase):
    def args(self,path):return SimpleNamespace(out=path,profile='smoke',seed=17)
    def test_missing_planned_check_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=P.Evidence('test',self.args(Path(tmp)/'out'),[],{},['first','second']);e.check('first',True,'ok')
            self.assertEqual(e.finish(),1);d=json.loads((e.out/'summary.json').read_text())
            self.assertFalse(d['complete']);self.assertEqual(d['planned'],2);self.assertEqual(d['results'][-1]['status'],'fail')
    def test_a_failed_check_fails_the_run_and_its_junit(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=P.Evidence('test',self.args(Path(tmp)/'out'),[],{},['first','second']);e.check('first',True,'ok');e.check('second',False,'why')
            self.assertEqual(e.finish(),1);d=json.loads((e.out/'summary.json').read_text())
            self.assertTrue(d['complete']);self.assertFalse(d['success'])
            suite=ET.parse(e.out/'junit.xml').getroot()
            self.assertEqual((suite.get('tests'),suite.get('failures')),('2','1'))
            self.assertEqual([c.get('name') for c in suite if c.find('failure') is not None],['second'])
        with tempfile.TemporaryDirectory() as tmp:
            e=P.Evidence('test',self.args(Path(tmp)/'out'),[],{},['first']);e.check('first',True,'ok')
            self.assertEqual(e.finish(),0);self.assertEqual(ET.parse(e.out/'junit.xml').getroot().get('failures'),'0')
        with self.assertRaises(ValueError),tempfile.TemporaryDirectory() as tmp:P.Evidence('test',self.args(Path(tmp)/'out'),[],{},[])
    def test_duplicate_and_unplanned_checks_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=P.Evidence('test',self.args(Path(tmp)/'out'),[],{},['first']);e.check('first',True,'ok')
            for name in ('first','other'):
                with self.assertRaises(ValueError):e.check(name,True,'bad')
    def test_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.args(Path(tmp)/'out');P.Evidence('test',args,[],{},['check'])
            with self.assertRaises(FileExistsError):P.Evidence('test',args,[],{},['check'])
class AxisSimulatorTests(unittest.TestCase):
    """The verdict of one AXI-Stream run, with stand-ins for the compiler and the simulator."""
    ROWS=[[1,1,0,15,1,1,1,1,0,15,1,0]]
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.tmp=Path(self.temp.name);self.number=0
    def tool(self,name,body):
        path=self.tmp/name;path.write_text('#!'+sys.executable+'\nimport json,sys\nif "-V" in sys.argv:print("test tool");sys.exit(0)\n'+body+'\n');path.chmod(0o755);return str(path)
    def simulator(self,build=0):
        iverilog=self.tool('iverilog',f'open(sys.argv[sys.argv.index("-o")+1],"w").close();sys.exit({build})')
        vvp=self.tool('vvp',f'spec=json.load(open({str(self.tmp/"vvp.json")!r}));print(spec["log"],end="")\n'
                      'if spec["wave"] is not None:open([a for a in sys.argv if a.startswith("+WAVE=")][0][6:],"w").write(spec["wave"])\nsys.exit(spec["code"])')
        args=SimpleNamespace(out=self.tmp/f'out{build}',profile='smoke',seed=17,timeout=10,iverilog=iverilog,vvp=vvp)
        sim=P.AxisSimulator(P.Evidence('test',args,[],{},['check']))
        self.good=''.join(f'COUNT {k}={v}\n' for k,v in sim.plugin.counts(self.ROWS).items())+'COVER goal/a\nRESULT PASS checks=1\n';return sim
    def run_case(self,sim,log,code=0,wave='$enddefinitions $end\n',**options):
        (self.tmp/'vvp.json').write_text(json.dumps(dict(log=log,code=code,wave=wave)));self.number+=1
        record=sim.execute(f'case{self.number}',self.ROWS,**options)
        self.assertEqual(json.loads((sim.e.out/record['id']/'result.json').read_text()),record);return record
    def verdict(self,*args,**options):
        record=self.run_case(*args,**options);return record['status'],record['message']
    def test_a_complete_run_passes_but_not_on_a_failed_build(self):
        sim=self.simulator();record=self.run_case(sim,self.good)
        self.assertEqual((record['status'],record['returncode'],record['coverage']),('pass',0,['goal/a']))
        sim=self.simulator(build=3)
        self.assertEqual(self.verdict(sim,self.good),('error','build failed'))
        self.assertEqual(self.verdict(sim,'CHECK_FAIL AXIS_META\n',1,mutation=1,expected='AXIS_META'),('error','build failed'))
        self.assertEqual([b[1]['returncode'] for b in sim.builds.values()],[3,3])
    def test_an_expected_failure_is_detected_only_by_its_own_label(self):
        sim=self.simulator();options=dict(mutation=1,expected='AXIS_META')
        self.assertEqual(self.verdict(sim,'CHECK_FAIL AXIS_META\n',1,**options)[0],'detected')
        self.assertEqual(self.verdict(sim,'CHECK_FAIL AXIS_DATA\n',1,**options),('error','mutation did not fail through the expected checker'))
        self.assertEqual(self.verdict(sim,'CHECK_FAIL AXIS_DATA\n',1,allow_clean=True,**options),('error','mutation did not fail through the expected checker'))
        self.assertEqual(self.verdict(sim,self.good,**options),('fail','mutation survived; expected AXIS_META'))
        self.assertEqual(self.verdict(sim,self.good,allow_clean=True,**options)[0],'pass')
        self.assertEqual(self.verdict(sim,'CHECK_FAIL AXIS_META\n',1,allow_clean=True,**options)[0],'detected')
    def test_a_passed_or_detected_run_without_its_waveform_is_an_error(self):
        sim=self.simulator()
        for name,log,code,expected in (('pass',self.good,0,None),('detected','CHECK_FAIL AXIS_META\n',1,'AXIS_META')):
            for wave in (None,'$scope module axis_tb $end\n'):
                with self.subTest(name,wave=wave):self.assertEqual(self.verdict(sim,log,code,wave,expected=expected),('error','waveform missing'))
    def test_missing_wrong_or_duplicate_counts_are_an_error(self):
        sim=self.simulator();first=self.good.splitlines(keepends=True)[0]
        for name,log in (('missing',self.good.replace(first,'')),('wrong',self.good.replace(first,'COUNT accepted=999\n')),('extra',self.good+'COUNT other=0\n'),('copied',self.good+first)):
            with self.subTest(name):self.assertEqual(self.verdict(sim,log),('error','count evidence differs'))
        self.assertEqual(self.verdict(sim,self.good,allow_clean=True,mutation=1,expected='AXIS_META')[0],'pass')
        self.assertEqual(self.verdict(sim,self.good+first,allow_clean=True,mutation=1,expected='AXIS_META'),('error','count evidence differs'))
    def test_coverage_is_credited_only_from_a_passing_run_of_the_unmodified_design(self):
        sim=self.simulator()
        self.assertEqual(self.run_case(sim,self.good)['coverage'],['goal/a'])
        record=self.run_case(sim,self.good,allow_clean=True,mutation=1,expected='AXIS_META');self.assertEqual((record['status'],record['coverage']),('pass',[]))
        record=self.run_case(sim,'COVER goal/a\nCHECK_FAIL AXIS_META\n',1,expected='AXIS_META');self.assertEqual((record['status'],record['coverage']),('detected',[]))
        record=self.run_case(sim,'COVER goal/a\nCHECK_FAIL AXIS_META\n',1);self.assertEqual((record['status'],record['coverage']),('fail',[]))
        sim.save();self.assertEqual([r['coverage'] for r in json.loads((sim.e.out/'executions.json').read_text())],[['goal/a'],[],[],[]])
if __name__=='__main__':unittest.main()
