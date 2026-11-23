from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-iommu')


def setup(p):
    p.step(rst=0)
    p.step(tup=1, sel=0, tvpn=0, tpfn=1, twr=1, tvb=1)  # vpn 0: RW, pfn 1
    p.step(tup=1, sel=1, tvpn=1, tpfn=2, twr=0, tvb=1)  # vpn 1: read-only, pfn 2
    p.step(tup=1, sel=2, tvpn=2, tpfn=3, twr=1, tvb=0)  # vpn 2 entry: invalid


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-iommu'
    GOALS = 14

    def test_miss_grants_three_cycles_later_hit_next_cycle(self):
        for parameters in P.CONFIGS.values():
            p = P.Plan(parameters['TLB'])
            setup(p)
            p.req(0)
            self.assertEqual(p.rows[-1][10], 0)
            p.idle()
            self.assertEqual(p.rows[-1][10], 1)  # the walk runs for two cycles
            p.idle()
            self.assertEqual(p.rows[-1][10], 1)
            p.idle()
            self.assertEqual(p.rows[-1][10:14], [0, 1, 1, 0])  # grant pfn 1
            p.req(0)
            p.idle()
            self.assertEqual(p.rows[-1][11], 1)  # the hit answers one cycle later

    def test_read_only_entry_faults_only_writes(self):
        p = P.Plan(3)
        setup(p)
        p.req(1, wr=1)
        for _ in range(3):
            p.idle()
        self.assertEqual(p.rows[-1][11:14], [1, 2, P.PERM])
        p.idle()
        p.req(1)  # the same entry serves reads with no fault
        p.idle()
        self.assertEqual(p.rows[-1][11:14], [1, 2, 0])

    def test_invalid_table_entry_is_a_miss_fault(self):
        p = P.Plan(1)
        setup(p)
        p.req(2)
        for _ in range(3):
            p.idle()
        self.assertEqual(p.rows[-1][11:14], [1, 0, P.MISS])
        self.assertEqual(p.rows[-1][15] & 1, 0)  # misses must not fill the TLB

    def test_update_invalidates_and_the_refetch_sees_the_new_pfn(self):
        p = P.Plan(1)
        setup(p)
        p.req(0)
        for _ in range(3):
            p.idle()
        self.assertEqual(p.rows[-1][15] & 1, 1)  # cached
        p.idle(tup=1, sel=0, tvpn=0, tpfn=9, twr=1, tvb=1)
        p.idle()  # the pins change on the row after the update
        self.assertEqual(p.rows[-1][15] & 1, 0)
        p.req(0)
        for _ in range(3):
            p.idle()
        self.assertEqual(p.rows[-1][12], 9)  # no stale pfn 1 survives

    def test_busy_backpressure_drops_and_reaccepts_requests(self):
        p = P.Plan(1)
        setup(p)
        p.req(0)
        p.req(1, wr=1)  # dropped while the walk runs
        self.assertEqual(p.rows[-1][10], 1)
        p.idle()
        self.assertEqual(p.rows[-1][10], 1)
        p.req(1, wr=1)  # busy is gone on this row: accepted, and vpn 0 grants here
        self.assertEqual(p.rows[-1][11:14], [1, 1, 0])
        p.idle()
        p.idle()
        self.assertEqual(p.rows[-1][10], 1)  # the vpn 1 request is walking
        p.idle()
        self.assertEqual(p.rows[-1][11:14], [1, 2, P.PERM])

    def test_out_of_range_updates_change_nothing(self):
        p = P.Plan(3)
        setup(p)
        p.idle(tup=1, sel=4, tvpn=3, tpfn=8, twr=1, tvb=1)
        p.idle(tup=1, sel=7, tvpn=0, tpfn=8, twr=0, tvb=1)
        p.req(0)
        for _ in range(3):
            p.idle()
        self.assertEqual(p.rows[-1][12], 1)  # vpn 0 keeps pfn 1, not 8
        p.req(3)
        for _ in range(3):
            p.idle()
        self.assertEqual(p.rows[-1][11:14], [1, 0, P.MISS])

    def test_stale_hit_after_invalidate_is_caught_on_the_pins(self):
        for parameters in P.CONFIGS.values():
            p = P.Plan(parameters['TLB'])
            setup(p)
            p.req(0)
            for _ in range(3):
                p.idle()
            p.idle(tup=1, sel=0, tvpn=0, tpfn=2, twr=1, tvb=1)
            p.idle()
            p.req(0)
            p.idle()
            p.idle()
            p.idle()
            p.idle()
            result = simulate_vectors(P, p.rows, parameters=parameters, replacements={'iommu.sv': [
                ('if (!hit && i < TLB && tlb_v[i] && tlb_evpn[i] == req_vpn)',
                 'if (!hit && i < TLB && tlb_evpn[i] == req_vpn)')]})
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('CHECK_FAIL IOMMU_XLAT', result.stdout)


if __name__ == '__main__':
    unittest.main()
