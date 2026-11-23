from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-clock-switch')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-clock-switch'
    GOALS = 11

    def test_startup_uses_boot_divider(self):
        for parameters in P.CONFIGS.values():
            p = P.Plan(parameters['BOOT'])
            p.step(rst=0)
            p.hold(2, ratio=parameters['BOOT'], idle=1)
            self.assertEqual(p.rows[-1][7], parameters['BOOT'])  # ratio列は始動分周比
            self.assertEqual(p.rows[-2][12], 0)                  # 起動直後はa系統

    def test_divider_loads_only_in_safe_window(self):
        p = P.Plan(1)
        p.step(rst=0)
        p.hold(6, ratio=1, idle=1)
        p.hold(4, ratio=4, idle=0)  # busy中: 安全ウィンドウでないのでratioは不動
        self.assertEqual(p.rows[-1][7], 1)
        p.hold(8, ratio=4, idle=1)  # idleが2エンジンサイクル続いた時点で反映
        self.assertEqual(p.rows[-1][7], 4)

    def test_switch_freezes_then_resumes_other_source(self):
        p = P.Plan(1)
        p.step(rst=0)
        p.hold(6, sel=0, ratio=1, idle=1)
        p.switch(1, 1)
        frozen = [row for row in p.rows if row[5]]
        self.assertTrue(frozen)  # 凍結ウィンドウ（switching=1）が観測できる
        # 凍結の翌行以降にエンジンパルスが残らないことはPlan不変条件が検証済み
        for _ in range(4):
            p.step(sel=1, ratio=1, idle=1)
        self.assertEqual(p.sel_q, 1)  # b系統へ切り替わった
        self.assertEqual(p.sw, 0)

    def test_switch_request_held_while_busy(self):
        p = P.Plan(1)
        p.step(rst=0)
        p.hold(6, ratio=1, idle=1)
        p.step(sel=1, ratio=1, idle=0)
        p.step(sel=1, ratio=1, idle=0)
        self.assertEqual(p.rows[-1][6], 1)  # busy_holdが立つ
        self.assertEqual(p.sw, 0)           # 凍結はまだ始まらない
        p.hold(2, sel=1, ratio=1, idle=1)
        self.assertEqual(p.sw, 1)           # idleになってから凍結が始まる

    def test_switching_window_shrinks_when_release_is_early(self):
        rows = P.vectors(17, 0, {'BOOT': 1}, True)
        rtl = simulate_vectors(P, rows,
                               replacements={'clock_switch.sv': [
                                   (': (!clk_a && !clk_b));', ': (!clk_a || !clk_b));')]})
        self.assertNotEqual(rtl.returncode, 0, rtl.stdout)
        self.assertIn('CHECK_FAIL CLK_SEL', rtl.stdout)


if __name__ == '__main__':
    unittest.main()
