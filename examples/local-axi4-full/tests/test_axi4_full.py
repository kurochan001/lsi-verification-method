import json
from pathlib import Path
import re
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
A=load_example('local-axi4-full');HERE=Path(__file__).resolve().parents[1]
TAG={i+1:t for i,t in enumerate(A.TAGS)}


def heads(rows):
    return [r for r in rows if r[0] in (A.WRITE,A.READ)]


class Axi4FullTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-axi4-full';GOALS=64

    def test_beat_addresses_and_lanes_against_hand_worked_values(self):
        starts=lambda *a:[b[0] for b in A.beat_bytes(*a)]
        self.assertEqual(starts(0x148,4,2,A.WRAP),[0x148,0x14c,0x140,0x144])
        self.assertEqual(starts(0x14c,4,2,A.WRAP),[0x14c,0x140,0x144,0x148])
        self.assertEqual(starts(0x24e,4,0,A.WRAP),[0x24e,0x24f,0x24c,0x24d])
        self.assertEqual(starts(0x264,3,2,A.FIXED),[0x264]*3)
        self.assertEqual(A.beat_bytes(0x301,2,2,A.INCR),[[0x301,0x302,0x303],[0x304,0x305,0x306,0x307]])
        self.assertEqual(A.beat_bytes(0x309,3,1,A.INCR),[[0x309],[0x30a,0x30b],[0x30c,0x30d]])
        self.assertEqual(A.beat_bytes(0x302,3,0,A.INCR),[[0x302],[0x303],[0x304]])
        self.assertEqual(A.beat_bytes(0x269,2,1,A.FIXED),[[0x269],[0x269]])

    def test_every_rejection_rule_alone_and_the_last_legal_request_next_to_it(self):
        self.assertEqual(A.problem(0x500,2,3,A.INCR),'size');self.assertIsNone(A.problem(0x500,2,2,A.INCR))
        self.assertEqual(A.problem(0x500,2,2,3),'burst')
        self.assertEqual(A.problem(0x500,3,2,A.WRAP),'wrap-length')
        for beats in (2,4,8,16):self.assertIsNone(A.problem(0x500,beats,2,A.WRAP))
        self.assertEqual(A.problem(0x502,4,2,A.WRAP),'wrap-unaligned');self.assertIsNone(A.problem(0x502,4,1,A.WRAP))
        self.assertEqual(A.problem(0x500,17,2,A.FIXED),'fixed-length');self.assertIsNone(A.problem(0x500,16,2,A.FIXED))
        self.assertIsNone(A.problem(0xff0,4,2,A.INCR));self.assertEqual(A.problem(0xff4,4,2,A.INCR),'4k')
        self.assertIsNone(A.problem(0xfff,1,0,A.INCR));self.assertEqual(A.problem(0xfff,2,0,A.INCR),'4k')
        self.assertIsNone(A.problem(0xffd,1,2,A.INCR));self.assertEqual(A.problem(0xffd,2,2,A.INCR),'4k')
        self.assertIsNone(A.problem(0xc00,256,2,A.INCR));self.assertEqual(A.problem(0xc04,256,2,A.INCR),'4k')
        self.assertIsNone(A.problem(0x1ff0,4,2,A.INCR));self.assertEqual(A.problem(0x1ff4,4,2,A.INCR),'4k')

    def test_model_memory_strobes_and_rejected_writes(self):
        p=A.Plan();p.write(0x10,[0x44332211])
        p.write(0x11,[0xffffffff],size=0,strobes=[15]);self.assertEqual(bytes(p.memory[0x10:0x14]),bytes([0x11,0xff,0x33,0x44]))
        p.write(0x10,[0xaabbccdd],strobes=[0b0101]);self.assertEqual(bytes(p.memory[0x10:0x14]),bytes([0xdd,0xff,0xbb,0x44]))
        before=bytes(p.memory)
        for request in (dict(burst=3),dict(size=3),dict(burst=A.WRAP)):
            self.assertEqual(p.write(0x10,[1,2,3],**request),A.SLVERR)
        self.assertEqual(p.write(0xff8,[1,2,3]),A.SLVERR);self.assertEqual(bytes(p.memory),before)
        self.assertEqual(p.write(0x20,[1,2,3],lasts=[0,1,0]),A.SLVERR);self.assertEqual(p.memory[0x28],3)
        p.write(0x30,[0x04030201,0x08070605,0x0c0b0a09,0x100f0e0d],burst=A.WRAP)
        p.write(0x38,[0xa4a3a2a1,0xb4b3b2b1,0xc4c3c2c1,0xd4d3d2d1],burst=A.WRAP)
        self.assertEqual(p.read(0x30,4),A.OKAY)
        self.assertEqual([r[1] for r in p.rows[-4:]],[0xc4c3c2c1,0xd4d3d2d1,0xa4a3a2a1,0xb4b3b2b1])
        p.read(0x31,1);self.assertEqual(p.rows[-1][1:4],[0xc4c3c200,0b1110,1])

    def test_exclusive_rules_in_the_model(self):
        p=A.Plan()
        self.assertEqual(p.read(0x40,1,ident=1,lock=1),A.EXOKAY);self.assertEqual(p.write(0x40,[5],ident=1,lock=1),A.EXOKAY)
        self.assertEqual(p.write(0x40,[6],ident=1,lock=1),A.OKAY);self.assertEqual(p.memory[0x40],5)
        p.read(0x40,1,ident=1,lock=1);p.write(0x43,[0x09000000],size=0,ident=2)
        self.assertEqual(p.write(0x40,[7],ident=1,lock=1),A.OKAY)
        p.read(0x40,1,ident=1,lock=1);p.write(0x3f,[0x09000000],size=0,ident=2);p.write(0x44,[9],size=0,ident=2)
        self.assertEqual(p.write(0x40,[8],ident=1,lock=1),A.EXOKAY)
        for request in ((0x40,3,2),(0x44,2,2),(0x40,32,0)):self.assertEqual(p.read(*request,lock=1),A.OKAY)
        self.assertEqual(p.read(0x40,2,burst=3,lock=1),A.SLVERR)
        p.read(0x40,1,ident=1,lock=1);p.read(0x40,1,ident=2,lock=1)
        self.assertEqual(p.write(0x40,[1],ident=2,lock=1),A.EXOKAY);self.assertEqual(p.write(0x40,[2],ident=1,lock=1),A.OKAY)
        p.read(0x40,1,ident=1,lock=1);p.reset();self.assertEqual(p.write(0x40,[3],ident=1,lock=1),A.OKAY)

    def test_tagged_rows_of_the_fixed_scenario_have_the_response_the_tag_names(self):
        expected={'excl/success':A.EXOKAY,'excl/second-write-fails':A.OKAY,'excl/fail-other-write':A.OKAY,'excl/adjacent-write-keeps':A.EXOKAY,
                  'excl/one-byte-overlap':A.OKAY,'excl/fail-mismatch':A.OKAY,'excl/other-id-attempt-keeps':None,'excl/race-loser':A.OKAY,
                  'excl/malformed-read':A.OKAY,'excl/multi-beat':A.EXOKAY,'excl/reset-clears':A.OKAY,'excl/normal-read-keeps':A.EXOKAY,
                  'excl/error-read':A.SLVERR,'boundary/4k-exact':A.OKAY,'boundary/memory-end':A.OKAY,'boundary/unaligned-last-bytes':A.OKAY}
        rows=A.boundary_vectors();seen=set()
        for row in heads(rows):
            name=TAG.get(row[11])
            if name is None:continue
            seen.add(name)
            if name.startswith('error/') and name!='error/no-write' or name.startswith('boundary/4k-cross'):
                self.assertEqual(row[7],A.SLVERR,(name,row))
            elif expected.get(name) is not None:self.assertEqual(row[7],expected[name],(name,row))
        tagged={TAG[r[11]] for r in rows if r[11]}
        self.assertEqual(tagged,set(A.TAGS))
        self.assertEqual({r[7] for r in heads(rows) if TAG.get(r[11])=='excl/other-id-attempt-keeps'},{A.OKAY,A.EXOKAY})

    def test_fixed_scenario_shape(self):
        rows=A.boundary_vectors();h=heads(rows)
        self.assertTrue(all(len(r)==12 for r in rows))
        self.assertEqual({r[4] for r in h if r[7]!=A.SLVERR},{A.FIXED,A.INCR,A.WRAP})
        self.assertEqual({r[2] for r in h if r[4]==A.WRAP and r[7]!=A.SLVERR},{2,4,8,16})
        self.assertEqual({r[3] for r in h if r[4]==A.WRAP and r[7]!=A.SLVERR},{0,1,2})
        self.assertIn(256,{r[2] for r in h if r[0]==A.WRITE});self.assertIn(256,{r[2] for r in h if r[0]==A.READ})
        self.assertTrue(any(r[0]==A.WRITE and r[10]&A.CHAIN for r in h) and any(r[0]==A.READ and r[10]&A.CHAIN for r in h))
        self.assertTrue(any(r[10]&A.W_FIRST for r in h))
        counts=A.counts(rows);self.assertEqual(counts['writes']+counts['reads'],len(h))
        self.assertEqual(counts['write_beats']+counts['read_beats']+len(h)+sum(r[0] in (A.IDLE,A.RESET) for r in rows),len(rows))

    def test_plan_refuses_requests_it_cannot_encode(self):
        with self.assertRaises(ValueError):A.Plan().write(8192,[0])
        with self.assertRaises(ValueError):A.Plan().read(0,257)
        with self.assertRaises(ValueError):A.Plan().write(0,[0,1],strobes=[15])
        p=A.Plan();p.write(0,[0],flags=A.CHAIN);p.read(0,1)
        with self.assertRaises(ValueError):p.finish()
        p=A.Plan();p.write(0,[0],flags=A.CHAIN);p.write(4,[0],flags=A.W_FIRST)
        with self.assertRaises(ValueError):p.finish()

    def test_random_vectors_reach_every_kind_of_request(self):
        rows=[r for seed in (17,18,19) for r in A.random_vectors(seed,400)];h=heads(rows)
        self.assertEqual({r[7] for r in h},{A.OKAY,A.EXOKAY,A.SLVERR})
        self.assertEqual({r[4] for r in h},{0,1,2,3});self.assertEqual({r[3] for r in h},{0,1,2,3})
        self.assertIn(256,{r[2] for r in h});self.assertTrue(any(r[0]==A.RESET for r in rows) and any(r[0]==A.IDLE for r in rows))
        self.assertTrue(any(r[10]&A.CHAIN for r in h) and any(r[10]&A.W_FIRST for r in h))
        self.assertTrue(any(r[0]==A.WRITE and r[6] and r[7]==A.OKAY for r in h))

    def test_goal_catalogue_tag_table_and_labels_agree_with_the_testbench(self):
        bench=(HERE/'tb/axi4_full_tb.sv').read_text()
        self.assertEqual(re.findall(r'(\d+):tag_name="([^"]+)";',bench),[(str(i+1),t) for i,t in enumerate(A.TAGS)])
        goals=[g for r in json.loads((HERE/'requirements.json').read_text())['requirements'] for g in r['goals']]
        self.assertEqual(len(goals),self.GOALS);self.assertTrue(set(A.TAGS)<=set(goals))
        labels=set(re.findall(r'"(AXF_[A-Z]+)"',bench))
        self.assertTrue(set(A.LABELS.values())<=labels);self.assertIn('AXF_TIMEOUT',labels-set(A.LABELS.values()))
        self.assertEqual(sorted(A.LABELS),list(range(1,A.MUTANTS+1)))

    def test_checker_labels_for_wrong_expectations_and_a_stuck_response(self):
        p=A.Plan();p.write(0x10,[0x44332211]);p.read(0x11,1);rows=p.finish()
        self.assertIn('RESULT PASS checks=4',simulate_vectors(A,rows).stdout)
        bad=[list(r) for r in rows];bad[3][1]^=0x00010000
        self.assertIn('CHECK_FAIL AXF_DATA',simulate_vectors(A,bad).stdout)
        bad=[list(r) for r in rows];bad[3][2]=0b1100
        self.assertIn('CHECK_FAIL AXF_LANE',simulate_vectors(A,bad).stdout)
        bad=[list(r) for r in rows];bad[3][3]=0
        self.assertIn('CHECK_FAIL AXF_LAST',simulate_vectors(A,bad).stdout)
        bad=[list(r) for r in rows];bad[0][7]=A.SLVERR
        self.assertIn('CHECK_FAIL AXF_RESP',simulate_vectors(A,bad).stdout)
        bad=[list(r) for r in rows];bad[2][7]=A.EXOKAY
        self.assertIn('CHECK_FAIL AXF_EXCL',simulate_vectors(A,bad).stdout)
        # A target that waits forever without breaking a rule ends through the timeout label, not a checker label.
        q=A.Plan();q.write(0x10,[1],ident=3)
        stuck=simulate_vectors(A,q.finish(),replacements={'axi4_full_ram.sv':[('assign bvalid=w_state==W_RESP;',"assign bvalid=w_state==W_RESP && w_id!=2'd3;"),
                                                                               ('W_RESP:if(bready)w_state<=W_IDLE;',"W_RESP:if(bready && w_id!=2'd3)w_state<=W_IDLE;")]}).stdout
        self.assertIn('CHECK_FAIL AXF_TIMEOUT',stuck);self.assertNotIn('RESULT PASS',stuck)
        # An unknown bit in a valid read beat is a mismatch, not a pass.
        q=A.Plan();q.write(0x10,[0x44332211]);q.read(0x10,1,ident=3)
        unknown=simulate_vectors(A,q.finish(),replacements={'axi4_full_ram.sv':[('assign rdata=r_data;',"assign rdata=r_data ^ {31'd0,r_id==2'd3 ? 1'bx:1'b0};")]}).stdout
        self.assertIn('CHECK_FAIL AXF_DATA',unknown);self.assertNotIn('RESULT PASS',unknown)


if __name__=='__main__':unittest.main()
