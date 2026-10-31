import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
S=importlib.util.spec_from_file_location('coord_runner',Path(__file__).resolve().parents[1]/'run.py');M=importlib.util.module_from_spec(S);S.loader.exec_module(M)
class CoordinationTests(unittest.TestCase):
    def test_same_edge_input_uses_old_gain_and_next_edge_uses_new_gain(self):
        rows=[[0,0,0,0,0,0,0,0,1],[1,1,1,1,0,3,0,0,1],[1,1,1,1,0,5,1,7,1],[1,0,0,0,0,0,1,7,1],[1,0,0,0,0,0,0,0,1]]
        trace,counts=M.model(rows);self.assertEqual(trace[2][5],21);self.assertEqual(trace[3][5],35);self.assertEqual(counts,dict(accepted=2,produced=2,cancelled=0,pending=0))
    def test_reset_cancels_only_outstanding_output(self):
        rows=[[1,1,1,1,0,3,0,0,1],[1,0,0,0,0,0,1,255,0],[0,0,0,0,0,0,0,0,0],[1,0,0,0,0,0,0,0,1]]
        trace,counts=M.model(rows);self.assertEqual(trace[1][5],255);self.assertEqual(counts,dict(accepted=1,produced=0,cancelled=1,pending=0))
    def test_generated_stimulus_holds_input_while_stalled_and_drains(self):
        for seed in (0,17,73):
            rows=M.vectors(seed,200);trace,counts=M.model(rows)
            for index in range(len(rows)-1):
                if rows[index][0] and rows[index][6] and not trace[index][1] and rows[index+1][0]:
                    self.assertEqual(rows[index+1][6:8],rows[index][6:8])
            self.assertEqual(counts['pending'],0);self.assertEqual(counts['accepted'],counts['produced']+counts['cancelled']);self.assertGreater(counts['cancelled'],0)
    def output(self,rows):
        trace,counts=M.model(rows)
        text=''.join('COORD_SAMPLE '+' '.join(str(v if v is not None else 0) for v in row)+'\n' for row in trace)
        return text+f"COORD_COMPLETE cycles={len(rows)} accepted={counts['accepted']} produced={counts['produced']} cancelled={counts['cancelled']} pending=0\n"
    def test_trace_rejects_missing_duplicate_unknown_and_changed_outputs(self):
        rows=M.vectors(17,2);good=self.output(rows);self.assertEqual(len(M.observed_trace(good,rows)[0]),len(rows))
        for text in (good+good,good.replace('COORD_SAMPLE 1 ','COORD_SAMPLE 2 ',1),good.replace('COORD_SAMPLE 1 ','COORD_SAMPLE x ',1),good.replace('pending=0','pending=1')):
            with self.assertRaises(ValueError):M.observed_trace(text,rows)
        lines=good.splitlines();index=next(i for i,line in enumerate(lines) if line.startswith('COORD_SAMPLE') and line.split()[5]=='1')
        words=lines[index].split();words[6]=str(int(words[6])^1);lines[index]=' '.join(words)
        with self.assertRaises(ValueError):M.observed_trace('\n'.join(lines)+'\n',rows)
    def native_fixture(self):
        lines=[]
        for name in sorted(M.BINS):lines.append(f"C '\x01t\x02covergroup\x01f\x02{M.HERE/'tb/coord_pkg.sv'}\x01h\x02{name}' 1\n")
        for name in sorted(M.COVERS):lines.append(f"C '\x01t\x02user\x01f\x02{M.HERE/'tb/top.sv'}\x01h\x02TOP.top.{name}\x01o\x02{name}' 1\n")
        return ''.join(lines),''.join('COORD_COVER '+n+'\n' for n in sorted(M.COVERS))
    def test_native_bins_are_exact_positive_and_source_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'coverage.dat';good,log=self.native_fixture();path.write_text(good)
            self.assertEqual(len(M.native(path,log)['bins']),23)
            for text,output in ((good+good,log),(good.replace("' 1","' 0",1),log),(good.replace(str(M.HERE),'/wrong-source'),log),(good,log+'COORD_COVER unexpected\n')):
                path.write_text(text)
                with self.assertRaises(ValueError):M.native(path,output)
    def test_unexpected_uvm_errors_and_missing_ownership_are_rejected(self):
        good='Accellera:1800.2:UVM:2020.3.2\nCOORD_OWNERSHIP config=1 data=1 ready=1\nUVM_WARNING x [NO_DPI_USED] expected\nUVM_WARNING x [NO_VISIT_CHECK] expected\nUVM_ERROR : 0\nUVM_FATAL : 0\nUVM_WARNING : 2\n'
        M.normal_report(good)
        for bad in (good.replace('UVM_ERROR : 0','UVM_ERROR : 1'),good.replace('config=1','config=0'),good.replace('2020.3.2','2020.3.1')):
            with self.assertRaises(ValueError):M.normal_report(bad)
if __name__=='__main__':unittest.main()
