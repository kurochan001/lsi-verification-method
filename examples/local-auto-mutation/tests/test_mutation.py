import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
s=importlib.util.spec_from_file_location('mutation_under_test',Path(__file__).resolve().parents[1]/'run.py');R=importlib.util.module_from_spec(s);s.loader.exec_module(R)
from task import sim_status
from vectors import step,vectors
class MutationTests(unittest.TestCase):
    def test_error_timeout_and_false_success_are_not_detections(self):
        self.assertEqual(sim_status(dict(error=None,returncode=1),'CHECK_FAIL IRQ_VALUE row=3\n',10),'FAIL')
        self.assertEqual(sim_status(dict(error=None,returncode=0),'MCY_COMPARE PASS checks=10\n',10),'PASS')
        for execution,log in [(dict(error='command timeout',returncode=1),'CHECK_FAIL IRQ_VALUE row=3\n'),(dict(error='missing executable',returncode=None),''),(dict(error=None,returncode=2),'syntax error'),(dict(error=None,returncode=1),'CHECK_FAIL IRQ_VALUE row=10\n'),(dict(error=None,returncode=0),'MCY_COMPARE PASS checks=0\n')]:
            self.assertIn(sim_status(execution,log,10),('ERROR','TIMEOUT'))
    def test_equivalent_conflict_and_incomplete_are_separate(self):
        self.assertEqual(R.tags_for('PASS','PASS','PASS'),{'EQUIVALENT'})
        self.assertEqual(R.tags_for('FAIL','PASS','PASS'),{'ORACLE_CONFLICT'})
        self.assertEqual(R.tags_for('FAIL','TIMEOUT','FAIL'),{'INCOMPLETE'})
        self.assertEqual(R.tags_for('PASS','FAIL','FAIL'),{'WEAK_UNCOVERED','STRONG_COVERED'})
    def test_event_wins_clear_and_masks_do_not_clear_pending(self):
        self.assertEqual(step(3,1,1,3,1),(1,1));self.assertEqual(step(2,1,0,0,0),(2,0));self.assertEqual(step(3,0,3,0,3),(0,0))
    def test_strong_vectors_cover_all_functional_transitions(self):
        data=vectors('strong');self.assertEqual(len(data),1536)
        combinations={(data[i+1][1],*data[i+2][:4]) for i in range(0,len(data),3)}
        self.assertEqual(len(combinations),512);self.assertEqual(len(vectors('weak')),33)
    def campaign(self,p,rows):
        (p/'database').mkdir()
        with closing(sqlite3.connect(p/'database/db.sqlite3')) as db,db:
            db.executescript('create table mutations(mutation_id integer,mutation text);create table results(mutation_id integer,test text,result text);create table tags(mutation_id integer,tag text);create table queue(task text);')
            for i,mutation,outcomes in rows:
                db.execute('insert into mutations values(?,?)',(i,mutation))
                source=p/'evidence'/str(i)/'mutated.v';source.parent.mkdir(parents=True);source.write_text('generated '+str(i))
                for kind,status in zip(('weak','strong','equiv'),outcomes):
                    directory=source.parent/kind;directory.mkdir();(directory/'result.json').write_text(json.dumps(dict(status=status,checks=33,mutated_sha256=R.Q.digest(source))))
                    db.execute('insert into results values(?,?,?)',(i,kind,status))
                for tag in R.tags_for(*outcomes):db.execute('insert into tags values(?,?)',(i,tag))
    def test_raw_database_evidence_and_score_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.campaign(p,[(1,R.NO_OP,['PASS','PASS','PASS']),(2,'mutate 2',['PASS','PASS','PASS']),(3,'mutate 3',['PASS','FAIL','FAIL'])])
            result=R.audit(p,3);self.assertEqual((result['candidates'],result['changed_mutations'],result['weak_score'],result['strong_score']),(2,1,0,1))
            (p/'evidence/3/mutated.v').write_text('changed after execution')
            with self.assertRaises(ValueError):R.audit(p,3)
    def test_no_op_control_is_required_and_is_not_an_equivalent_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.campaign(p,[(1,R.NO_OP,['PASS','PASS','PASS']),(2,'mutate 2',['PASS','FAIL','FAIL'])])
            result=R.audit(p,2);self.assertEqual(result['counts']['EQUIVALENT'],0);self.assertEqual(result['no_op_control']['id'],1);self.assertEqual(len(result['mutations']),1)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.campaign(p,[(1,'mutate 1',['PASS','PASS','PASS'])])
            with self.assertRaisesRegex(ValueError,'no-op control missing'):R.audit(p,1)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);self.campaign(p,[(1,R.NO_OP,['PASS','FAIL','PASS'])])
            with self.assertRaisesRegex(ValueError,'not equivalent'):R.audit(p,1)
if __name__=='__main__':unittest.main()
