#!/usr/bin/env python3
"""XY routing, backpressure, head-of-line blocking and liveness in a 2x2 mesh NoC."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-noc-mesh'
TOP = 'mesh2x2_tb'
CONFIGS = {'buf1': {'BUF': 1}, 'buf2': {'BUF': 2}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/router.sv', HERE / 'rtl/mesh2x2.sv', HERE / 'tb/mesh2x2_tb.sv']

# ノード番号は n = 2*y + x（0:(0,0) 1:(1,0) 2:(0,1) 3:(1,1)）。
# 出力ポートは 0=LOCAL 1=E(+x) 2=N(+y)。FIFO入力ポートは 0=自ノード注入 1=W入力（n-1のE出力から）
# 2=S入力（n-2のN出力から）。XYルーティングは+x→+yの順で、引き返し方向のパケットは注入時に破棄する。
DLINK = {(0, 1): (1, 1), (2, 1): (3, 1), (0, 2): (2, 2), (1, 2): (3, 2)}
UP = {1: [(0, 1, 1)], 2: [(0, 2, 2)], 3: [(2, 1, 1), (1, 2, 2)]}


def pack(dst, src, seq, data):
    # flit 12ビット = dst(2) src(2) seq(4) data(4)
    return ((dst & 3) << 10) | ((src & 3) << 8) | ((seq & 0xf) << 4) | (data & 0xf)


def route_of(r, dst):
    """自ノード r から dst へ向かう次の出力ポート。XYで後方になり引き返せないならNone。"""
    if not reachable(r, dst):
        return None
    if dst == r:
        return 0
    if (dst & 1) > (r & 1):
        return 1
    return 2


def reachable(r, dst):
    """XY次元順で dst へ到達できるか。+x/-yのように途中で引き返す必要があればFalse。"""
    return (dst & 1) >= (r & 1) and (dst >> 1) >= (r >> 1)


class Plan:
    """サイクル精度の参照モデル。毎サイクル期待値の行を1本作る（1行=1つのtckサイクル）。"""

    def __init__(self, buf):
        self.buf = buf
        self.rows = []
        self.reset()

    def reset(self):
        self.fifo = [[[], [], []] for _ in range(4)]  # ルータごとの入力FIFO（1スロット=パケット1個）
        self.outp = [[None] * 3 for _ in range(4)]    # 出力保持段 0=LOCAL 1=E 2=N
        self.ptr = [[0] * 3 for _ in range(4)]        # 出力ポートごとのラウンドロビン・ポインタ
        self.seq = [0] * 4
        self.steps = 0
        self.idle = 0

    def ready_bits(self):
        return sum(1 << n for n in range(4) if len(self.fifo[n][0]) < self.buf)

    def settled(self):
        return not any(q for r in self.fifo for q in r) and not any(p for r in self.outp for p in r)

    def step(self, rst=1, inj_valid=0, inj_flit=0, e_ready=15):
        if not rst:
            self.rows.append([0, 0, 0, 0xF, 0, 0, 0, 0, 0])
            self.reset()
            self.steps += 1
            return
        occ = [[len(q) for q in ports] for ports in self.fifo]
        outp = self.outp
        # --- エッジ前: 配信、スタル、仲裁 ---
        deliver = {n: outp[n][0] for n in range(4) if outp[n][0] is not None and (e_ready >> n) & 1}
        stall = [0] * 4
        for n, links in UP.items():
            for src, port, ip in links:
                pending = outp[src][port] is not None or any(
                    q and route_of(src, q[0][0]) == port for q in self.fifo[src])
                if pending and occ[n][ip] >= self.buf:
                    stall[n] = 1
        grants = {}
        for r in range(4):
            for port in (0, 1, 2):
                if port == 1 and (r & 1):
                    continue
                if port == 2 and (r >> 1):
                    continue
                ptr = self.ptr[r][port]
                cands = [ip for ip in ((ptr + k) % 3 for k in range(3))
                         if self.fifo[r][ip] and route_of(r, self.fifo[r][ip][0][0]) == port]
                if not cands:
                    continue
                if port == 0 and outp[r][0] is not None and r not in deliver:
                    continue
                if port and occ[DLINK[(r, port)][0]][DLINK[(r, port)][1]] >= self.buf:
                    continue
                grants[(r, port)] = (cands[0], self.fifo[r][cands[0]][0])
                self.ptr[r][port] = (cands[0] + 1) % 3
        rows = [1, inj_valid, inj_flit, self.ready_bits(), e_ready]
        rows += stall   # 期待行: rst,注入valid,flit,ready,出口ready, stall×4（計9列）
        self.rows.append(rows)
        # --- エッジ適用: ポップ → リンク転送 → 保持段ロード → 注入 ---
        for (r, port), (ip, pkt) in grants.items():
            self.fifo[r][ip].pop(0)
        for (r, port), (down, dip) in DLINK.items():
            if outp[r][port] is not None and occ[down][dip] < self.buf:
                self.fifo[down][dip].append(outp[r][port])
                outp[r][port] = None    # 転送完了で保持段を空ける（grantはその後で積む）
        for n in deliver:
            outp[n][0] = None
        for (r, port), (ip, pkt) in grants.items():
            outp[r][port] = pkt
        for n in range(4):
            dst = (inj_flit >> 10) & 3
            if ((inj_valid >> n) & 1) and occ[n][0] < self.buf and reachable(n, dst):
                self.fifo[n][0].append((dst, (inj_flit >> 4) & 0xf, inj_flit & 0xf))
        self.steps += 1

    def inject(self, src, dst, data, e_ready=15):
        seq = self.seq[src]
        self.seq[src] = (seq + 1) & 0xf
        self.step(inj_valid=1 << src, inj_flit=pack(dst, src, seq, data), e_ready=e_ready)

    def send(self, src, dst, data):
        while not (self.ready_bits() >> src) & 1:
            self.step()
        self.inject(src, dst, data)
        self.step()

    def drain(self, tail=6):
        for _ in range(200):
            if self.settled():
                break
            self.step()
        else:
            raise RuntimeError("reference mesh did not drain with all egress ports open")
        for _ in range(tail):
            self.step()

    def fixed(self):
        self.step(rst=0)
        # XY 1ホップ（+x方向）。注入後1サイクル押してから配信する。
        self.send(0, 1, 0x31)
        self.drain()
        for _ in range(202):
            self.step()  # bound the first delivery before subsequent traffic or reset
        # XY 1ホップ（+y方向）。
        self.send(0, 2, 0x31)
        self.drain()
        # XY 2ホップ（0→1→3でx→yの順）。
        self.send(0, 3, 0x32)
        self.drain()
        # 引き返し方向のパケットは注入時に破棄される（無効な宛先）。
        self.send(3, 0, 0x33)
        for _ in range(4):
            self.step()
        self.drain()
        # ラウンドロビン仲裁: 0→3（1の中継）と1→3（1の自ノード）がノード1のN出力で競合し、
        # 後から入った1→3が先に流れる。どちらも遅れずに配信される。
        self.inject(0, 3, 0x34)
        self.step()
        self.inject(1, 3, 0x35)
        self.drain()
        # 多重ストリーム: 4系統を連続注入し、初配信前に複数ソースが配線へ列挙する。
        self.inject(0, 0, 0x40)
        self.inject(2, 2, 0x41)  # back-to-back deliveries even with one-entry input FIFOs
        self.drain()
        self.send(0, 1, 0x40)
        self.inject(2, 3, 0x41)
        self.send(0, 3, 0x42)
        self.inject(1, 3, 0x43)
        self.drain()
        # HOL: ノード1の出口を抑え、+x出力を詰まらせ、注入FIFOの 0→2 を 0→1 の後ろへ遅らせる。
        # BUF1では詰まりが1つ手前のルータまで見える（stallピン）。
        for src, dst, data in [(0, 1, 0x36), (0, 1, 0x37), (0, 1, 0x38), (0, 1, 0x3a),
                               (0, 2, 0x39), (0, 1, 0x45), (0, 1, 0x46), (0, 1, 0x47), (0, 1, 0x48)]:
            if (self.ready_bits() >> src) & 1:
                self.inject(src, dst, data, e_ready=13)   # 詰まったポートへの注入は待たない
            else:
                self.step(inj_valid=1 << src, inj_flit=pack(dst, src, self.seq[src], data), e_ready=13)
                self.seq[src] = (self.seq[src] + 1) & 0xf
        for _ in range(6):
            self.step(e_ready=13)
        self.drain()
        # 生きた閉ループ要求: XYでは引き返しが必要なので 1→0 は注入時に破棄される。
        # 0→1 と 2→3 の同時フローは帯域を奪い合っても取りこぼしなく流れ切る。
        self.send(1, 0, 0x3b)
        self.send(0, 1, 0x3c)
        self.inject(2, 3, 0x3d)
        self.drain()
        # リセット中断→復帰: 2パケットを飛行させてからリセットし、破棄後の再送を確認する。
        self.inject(0, 3, 0x3e)
        self.inject(2, 3, 0x3f)
        self.step()
        self.step(rst=0)
        self.step()
        self.send(0, 1, 0x44)
        self.drain()

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            roll = rng.randrange(100)
            if roll < 5:
                self.step(rst=0)
                continue
            e_ready = 15 if roll < 55 else rng.randrange(16)
            if roll < 75:
                src = rng.randrange(4)
                dst = rng.randrange(4)
                wait = 0
                while not (self.ready_bits() >> src) & 1:
                    # 出口を抑えたまま注入先が満タンで止まらないよう、少し待ったら解放する
                    self.step(e_ready=15 if wait >= 6 else e_ready)
                    wait += 1
                self.inject(src, dst, rng.randrange(64), e_ready=e_ready)
            self.step(e_ready=e_ready)


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['BUF'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    p.drain()
    # ライブネス検証: 最後の注入から200サイクル以内に全配信が終わっていることを
    # テストベンチ側の待機カウンタで確かめるための無操作行（正設計では配信は既に無い）。
    for _ in range(210):
        p.step()
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'MESH_DATA'), (2, 'MESH_BP'), (3, 'MESH_LIVE'), (4, 'MESH_ROUTE')):
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
