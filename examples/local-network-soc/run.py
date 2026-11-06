#!/usr/bin/env python3
"""ROM-booted RV32I + RAM + AHB-Lite/APB + AXI4 packet DMA + bounded Ethernet NIC."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('network_soc_support',HERE.parent/'local-network-echo/support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E;M=S.MODEL;F=S.load('network_firmware',HERE/'firmware.py')
CONFIGS={'bytes96-fast':dict(MAX_FRAME=96,WAIT_CYCLES=0),'bytes128-wait':dict(MAX_FRAME=128,WAIT_CYCLES=2)}
SOURCES=[*sorted((HERE/'rtl').glob('*.sv')),*sorted((HERE.parent/'local-network-echo/rtl').glob('*.sv')),
    *[HERE.parent/'local-image-soc/rtl'/n for n in ('cpu_ahb.sv','image_fabric.sv','image_memory.sv')],
    HERE.parent/'local-riscv-iss/rtl/rv32i_core.sv',HERE.parent/'local-riscv-decoder/rtl/rv32i_decoder.sv',HERE/'tb/network_soc_tb.sv']


def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=['arp-udp','boundaries','reject','overflow','rx-error','tx-error','rx-error-mid','rx-error-last','tx-error-mid','tx-error-last','relocated','w1c-race','bus-errors','reset-rx','reset-dma-tx','reset-wire-tx','detect-rom-compare',*[f'random-{s}' for s in seeds],*[f'mutation-{i}' for i in range(1,5)]]
    e=E.Evidence('local-network-soc',a,[Path(__file__),HERE/'firmware.py',HERE.parent/'local-network-echo/model.py',HERE.parent/'local-network-echo/support.py',HERE/'requirements.json',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),
        ['toolchain',*[cfg+'/'+name for cfg in CONFIGS for name in [*names,'coverage']],'source-freshness'])
    sim=S.Simulator(e,'network_soc_tb',SOURCES)
    probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,pars in CONFIGS.items():
        limit=pars['MAX_FRAME']
        def execute(name,frames,seed=a.seed,scenario=0,mutation=0,label=None,overflow=False,fault=-1,bases=(0x1000,0x1400),race=False,corrupt=False):
            selected=frames[:3] if overflow else frames
            decoded=[(f,M.decode(f['data'] if isinstance(f,dict) else f,limit,f.get('link_error',False) if isinstance(f,dict) else False)[0]) for f in selected]
            admitted=[f for f,r in decoded if r is not None];golden=[r for _,r in decoded if r is not None]
            replies=[] if scenario in (1,2) else golden;drops=len(frames)-len(golden)
            counts=dict(rx_frames=len(frames),tx_frames=len(replies),tx_bytes=sum(map(len,replies)),drops=drops,resets=int(scenario in (3,4,5)))
            rows=M.rows(frames,seed,mode='overflow' if overflow else 'sequential')
            # SoC completion is event-based; no fixed long drain is needed in the input file.
            rows=rows[3:-1500]
            while rows and not rows[-1][1]:rows.pop()
            stage=3 if scenario==6 else 4 if race else scenario if scenario<3 else 0
            table=[bytes((r[0]^1,*r[1:])) for r in golden] if corrupt else golden
            image=dict(max_frame=limit,drops=drops,scenario=stage,rx_base=bases[0],tx_base=bases[1])
            plusargs=dict(FAULT=fault,RX_BASE=bases[0],TX_BASE=bases[1],COMPARE_PC=F.compare_pc(table,**image),CPU_CHECKS=0 if scenario==1 else sum(map(len,golden)),APB_ERRORS=F.rejected_accesses(stage,limit,len(golden)))
            return sim.execute(cfg+'/'+name,pars,frames,replies,rows,seed,counts,mutation,label,scenario,F.program(table,**image),[] if scenario==1 else golden,M.expect_drops(frames,limit,range(len(selected))),admitted,plusargs)
        execute('arp-udp',[M.arp(),M.udp(b'odd'),M.udp(b'',zero_checksum=True)])
        execute('boundaries',[M.udp(bytes(range(limit-46))),M.zero_result_packet()])
        execute('reject',M.invalid_frames(limit))
        execute('overflow',[M.udp(bytes((i,1,2))) for i in range(5)],overflow=True)
        execute('bus-errors',[M.arp(),M.udp(b'bus')],scenario=6)
        execute('rx-error',[M.arp()],scenario=1);execute('tx-error',[M.udp(b'error')],scenario=2)
        # One bad response only, in the middle and on the last beat of the 64-byte frame.
        for suffix,beat in (('mid',3),('last',63)):
            execute('rx-error-'+suffix,[M.arp()],scenario=1,fault=beat);execute('tx-error-'+suffix,[M.udp(b'error')],scenario=2,fault=beat)
        # Both buffers away from their reset values, ending exactly at the top of RAM.
        execute('relocated',[M.arp(),M.udp(b'moved')],bases=(0x2000-4*limit,0x1000))
        execute('w1c-race',M.invalid_frames(limit)*2,race=True)
        execute('detect-rom-compare',[M.arp()],corrupt=True,label='NET_SOC_COMPLETION')
        for scenario,name in enumerate(('reset-rx','reset-dma-tx','reset-wire-tx'),3):execute(name,[M.arp(),M.udp(b'reset')],scenario=scenario)
        for seed in seeds:execute(f'random-{seed}',M.random_frames(limit,seed,3),seed)
        for i,label in enumerate(('NET_SOC_RX_ORDER','NET_SOC_AXI','NET_SOC_OWNERSHIP','NET_SOC_TX_ORDER'),1):
            execute(f'mutation-{i}',[M.arp(),M.udp(b'ownership')],mutation=i,label=label)
        hits=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage']);coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits));e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()


def main():
    p=E.parser(__doc__,'local-network-soc');a=p.parse_args();E.validate(p,a)
    if a.seed>2**31-4:p.error('seed must fit three signed 32-bit simulation seeds')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
