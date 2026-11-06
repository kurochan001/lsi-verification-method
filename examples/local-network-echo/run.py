#!/usr/bin/env python3
"""Unthrottled Ethernet RX, bounded frame queue, FCS/ARP/IPv4/UDP validation and echo."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('network_support',HERE/'support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E;M=S.MODEL
CONFIGS={'bytes96':dict(MAX_FRAME=96),'bytes128':dict(MAX_FRAME=128)}
SOURCES=[*sorted((HERE/'rtl').glob('*.sv')),HERE/'tb/network_tb.sv']


def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=['directed','reject','overflow','recover','swap-exact','swap-early','reset-rx','reset-tx',*[f'random-{s}' for s in seeds],*[f'mutation-{i}' for i in range(1,5)]]
    e=E.Evidence('local-network-echo',a,[Path(__file__),HERE/'model.py',HERE/'support.py',HERE/'requirements.json',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),
        ['toolchain',*[cfg+'/'+name for cfg in CONFIGS for name in [*names,'coverage']],'source-freshness'])
    sim=S.Simulator(e,'network_tb',SOURCES);probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,pars in CONFIGS.items():
        limit=pars['MAX_FRAME']
        def execute(name,frames,seed=a.seed,mode='sequential',reset=None,mutation=0,label=None):
            admitted=(0,1,2) if mode in ('overflow','swap-early') else (0,1,2,4) if mode=='recover' else range(len(frames))
            selected=[frames[i] for i in admitted];fate=M.expect_drops(frames,limit,admitted)
            replies=[r for f in selected if (r:=M.decode(f['data'] if isinstance(f,dict) else f,limit,f.get('link_error',False) if isinstance(f,dict) else False)[0]) is not None]
            counts=dict(rx_frames=len(frames),tx_frames=len(replies),tx_bytes=sum(map(len,replies)),drops=len(frames)-len(replies),resets=int(reset is not None))
            return sim.execute(cfg+'/'+name,pars,frames,replies,M.rows(frames,seed,mode,reset),seed,counts,mutation,label,drops=fate)
        execute('directed',M.directed(limit));execute('reject',M.invalid_frames(limit)+[M.udp(b'recovered')])
        burst=[M.udp(bytes((i,1,2)),source_port=2100+i,identification=i) for i in range(5)]
        execute('overflow',burst,mode='overflow');execute('recover',burst,mode='recover')
        execute('swap-exact',burst[:4],mode='swap-exact');execute('swap-early',burst[:4],mode='swap-early')
        execute('reset-rx',[M.arp(),M.udp(b'reset')],reset='receive');execute('reset-tx',[M.arp(),M.udp(b'reset')],reset='transmit')
        for seed in seeds:execute(f'random-{seed}',M.random_frames(limit,seed,10 if a.profile=='nightly' else 4),seed)
        execute('mutation-1',[M.invalid_frames(limit)[0]],mutation=1,label='NET_UNEXPECTED')
        execute('mutation-2',[M.udp(b'checksum')],mutation=2,label='NET_FRAME')
        execute('mutation-3',[M.udp(b'odd')],mutation=3,label='NET_FRAME')
        execute('mutation-4',[M.arp()],mutation=4,label='NET_HOLD')
        hits=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage']);coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits));e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()


def main():
    p=E.parser(__doc__,'local-network-echo');a=p.parse_args();E.validate(p,a)
    if a.seed>2**31-4:p.error('seed must fit three signed 32-bit simulation seeds')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
