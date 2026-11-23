#!/usr/bin/env python3
"""Glitch-free clock switching with a DVFS divider checked by exact edge counts."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-clock-switch'
TOP = 'clock_switch_tb'
CONFIGS = {'boot1': {'BOOT': 1}, 'boot4': {'BOOT': 4}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/clock_switch.sv', HERE / 'tb/clock_switch_tb.sv']


class Plan:
    """RTLと1対1で対応するgolden model。全クロックは4nsグリッド上の整数周期。

    行ベクトルはTBと同じタイムラインで進む。行iはposedge_iのあとの状態を表し、
    その行のsel/div/idle入力は次のposedge_{i+1}でRTLに入る。TBのカウンタが
    1エッジ遅れで数えるエンジンエッジもそのまま再現する。
    """

    def __init__(self, boot):
        self.boot = boot
        self.rows = []
        self.sel_in, self.ratio_in, self.idle_in = 0, 1, 1
        self.reset_model()

    @property
    def sel_q(self):
        return self.sel_reg

    def reset_model(self):
        self.qa = self.qb = 0
        self.a = self.b = 0
        self.sel_reg = self.ar = self.br = self.sw = 0
        self.engine = self.raw_p = 0
        self.ratio = self.div_pend = self.boot
        self.phase = self.idle_run = self.busy_hold = 0
        self.ecount = self.rise = 0

    def step(self, rst=1, sel=0, ratio=1, idle=1):
        self.sel_in, self.ratio_in, self.idle_in = sel, ratio, idle
        div = ratio - 1
        if not rst:
            row = [0, sel, div, idle, 0, 0, 0, self.boot, 0, 0, self.boot, 0, 0]
            self.check_invariants(row)
            self.rows.append(row)
            self.reset_model()
            self._clocks()  # リセット行のあとのposedgeでは光源カウンタだけが次に進む
            return
        row = [1, sel, div, idle, self.engine, self.sw, self.busy_hold, self.ratio,
               self.idle_run, self.ecount, self.div_pend, self.phase, self.sel_q]
        self.check_invariants(row)
        self.rows.append(row)
        self._advance(sel, div, idle)

    def check_invariants(self, row):
        # TBと同じ2つのグリッチ不変条件: 凍結ウィンドウの1周期あとまで出力が
        # 残らないこと、系統が入れ替わった行で出力がHighのままではないこと。
        prev = self.rows[-1] if self.rows else None
        if prev and row[4] and prev[5]:
            raise AssertionError('switchingのあとにengine_clkが残った')
        if prev and row[4] and row[12] != prev[12]:
            raise AssertionError('系統入替わりにengine_clkがHigh')

    def _clocks(self):
        self.qa ^= 1                    # clk_a: 周期2グリッド(8ns)
        self.qb = 0 if self.qb == 2 else self.qb + 1  # clk_b: 周期3グリッド(12ns)
        self.a = self.qa
        self.b = 1 if self.qb == 0 else 0

    def _advance(self, sel, div, idle):
        sel_q, ar, br, sw, bh = self.sel_reg, self.ar, self.br, self.sw, self.busy_hold
        ratio, div_pend, phase, idle_run = self.ratio, self.div_pend, self.phase, self.idle_run
        raw = (self.b if sel_q else self.a) & (ar | br)
        engine_old, raw_p = self.engine, self.raw_p
        raw_tick = raw and not raw_p
        # engine_qはposedge入力で決まるレジスタ出力。ゲートは更新前のratio/phaseで決める
        engine_new = int(raw and (ratio == 1 or phase == ratio - 1))
        ecount = self.ecount + self.rise           # TBは1エッジ遅れでエンジンエッジを数える
        load = idle_run >= 2 and ratio != div_pend  # 安全ウィンドウでの分周比ロード判定
        # RTLのalwaysブロック（非ブロッキングで後勝ち）を逆順に適用し、先勝ちで再現する
        if ratio != div_pend:
            phase = 0                              # 安全ウィンドウ待ちのあいだはエッジを出さない
        if raw_tick:
            idle_run = 0 if not idle else min(3, idle_run + 1)
            if ratio == div_pend:
                phase = 0 if phase >= ratio - 1 else phase + 1
        elif not idle:
            idle_run = 0
        if load:
            ratio = div_pend
        if not sw and not ar and not br and sel == sel_q:  # 凍結外のエンジン停止中のみ起動
            if sel:
                br = 1
            else:
                ar = 1
        if not sw and sel != sel_q and not idle:   # busy中の切替要求は保留
            bh = 1
        if bh and sel == sel_q:                    # 要求が取り下げられたら保留を解く
            bh = 0
        if sw and not self.a and not self.b:       # 凍結解除: 両系統Lowで新系統を流す
            sel_q = sel
            sw = 0
            if sel:
                br = 1
            else:
                ar = 1
        if not sw and sel != sel_q and idle:       # 旧系統のHighが明けたら凍結開始
            if not (self.b if sel_q else self.a):
                if sel_q:
                    br = 0
                else:
                    ar = 0
                sw = 1
        self._clocks()
        self.sel_reg = sel_q
        self.ar, self.br, self.sw, self.busy_hold = ar, br, sw, bh
        self.ratio, self.div_pend, self.phase, self.idle_run = ratio, div + 1, phase, idle_run
        self.raw_p = raw
        self.engine = engine_new
        self.ecount, self.rise = ecount, int(engine_new and not engine_old)

    def hold(self, cycles, sel=None, ratio=None, idle=None):
        for _ in range(cycles):
            self.step(sel=self.sel_in if sel is None else sel,
                      ratio=self.ratio_in if ratio is None else ratio,
                      idle=self.idle_in if idle is None else idle)

    def switch(self, sel, ratio, busy=0):
        for _ in range(3 if busy else 0):
            self.step(sel=sel, ratio=ratio, idle=0)
        for _ in range(30):
            self.step(sel=sel, ratio=ratio, idle=1)
            if self.sw or self.sel_q == sel:
                self.step(sel=sel, ratio=ratio, idle=1)  # 凍結状態を行として残す
                return
        raise AssertionError('切替要求が受理されない')

    def finish_switch(self, ratio, cycles):
        for _ in range(30):
            if not self.sw:
                break
            self.step(sel=self.sel_in, ratio=ratio, idle=1)
        self.hold(cycles, ratio=ratio, idle=1)

    def fixed(self):
        self.step(rst=0)
        self.hold(4, sel=0, ratio=1, idle=1)
        self.hold(2, ratio=1, idle=0)   # idle=0で連続アイドルカウンタをリセット
        self.hold(3, ratio=2, idle=1)   # /2はidleが続いた安全ウィンドウでのみ反映
        self.hold(8, ratio=2, idle=1)
        self.hold(1, ratio=8, idle=1)   # /8をリクエスト
        self.hold(2, ratio=8, idle=0)   # busy中: 分周比は動かない
        self.hold(8, ratio=8, idle=1)
        self.hold(1, ratio=1, idle=1)
        self.hold(8, ratio=1, idle=1)
        self.switch(1, 1, busy=1)      # エンジン起動中にb側へ: 保留されてから切替
        self.finish_switch(1, 8)
        self.switch(0, 1)              # a側へ戻る
        self.finish_switch(1, 8)
        self.switch(1, 4)              # 切替中に分周比もリクエスト: 凍結中は不動
        self.finish_switch(4, 10)
        self.switch(0, 2)
        self.finish_switch(2, 10)
        self.step(rst=0)
        self.hold(4, sel=0, ratio=2, idle=1)  # リセット復帰: 始動分周比から再設定

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            roll = rng.randrange(100)
            if roll < 8:
                self.step(rst=0)
            elif roll < 16:
                self.step(ratio=rng.randrange(1, 9))
            elif roll < 30:
                self.switch(1 - self.sel_in, rng.randrange(1, 9), busy=rng.randrange(2))
            else:
                self.hold(rng.randrange(1, 4), idle=rng.randrange(2))


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['BOOT'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    p.hold(2)
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'CLK_GLITCH'), (2, 'CLK_SEL'), (3, 'CLK_DIV'), (4, 'CLK_SEL')):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))
