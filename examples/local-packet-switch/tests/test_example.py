from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-packet-switch')

class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-packet-switch';GOALS=14
    def check_rtl(self,rows,parameters=None):
        r=simulate_vectors(P,rows,parameters=parameters)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_round_robin_changes_only_at_packet_tail(self):
        p=P.Plan(8);p.cycle(rst=0)
        p.streams([P.packet(0,[10,11])+P.packet(0,[12]),P.packet(0,[20,21])+P.packet(0,[22])])
        transferred=[r[9]&255 for r in p.rows if r[7]&r[5]&1]
        self.assertEqual(transferred,[10,11,20,21,12,22]);self.check_rtl(p.rows)

    def test_held_header_keeps_owner_when_preferred_contender_arrives(self):
        p=P.Plan(8);p.cycle(rst=0);p.cycle([None,(0,0,21)],ready=0)
        p.cycle([(0,1,10),(0,0,21)],ready=0)
        self.assertEqual([r[9]&255 for r in p.rows[-2:]],[21,21])
        p.streams([P.packet(0,[10]),P.packet(0,[21,22])]);self.check_rtl(p.rows)

    def test_input_gap_and_body_destination_do_not_release_output(self):
        p=P.Plan(8);p.cycle(rst=0);p.cycle([(1,0,11),None])
        for _ in range(3):self.assertEqual(p.cycle([None,(1,1,21)]),0)
        p.streams([[(0,1,12)],[(1,1,21)]])
        self.assertEqual([r[9]>>8 for r in p.rows if r[7]&r[5]&2],[11,12,21]);self.check_rtl(p.rows)

    def test_reset_abandons_partial_packet_then_restarts_routing(self):
        p=P.Plan(8);p.cycle(rst=0);p.cycle([(0,0,11),None]);p.cycle(rst=0)
        p.streams([P.packet(1,[12]),P.packet(0,[21])]);self.check_rtl(p.rows)

if __name__=='__main__':unittest.main()
