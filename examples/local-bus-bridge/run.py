#!/usr/bin/env python3
"""AHB-Lite/AXI4-Lite to APB3 integration with independent timed transactions."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-bus-bridge';TOP='bridge_tb'
CONFIGS={f'{b}-wait{w}':dict(BUS=i,WAIT_CYCLES=w) for i,b in enumerate(('ahb','axi')) for w in (0,2)}
ITERATIONS={'smoke':32,'nightly':300}
CHECK=HERE.parent/'local-bus-validation/checkers'
SOURCES=[HERE/'rtl/bus_bridge.sv',HERE.parent/'local-apb/rtl/apb_regs.sv',
         HERE.parent/'local-apb-timer/rtl/apb_timer.sv',HERE.parent/'local-timer-watchdog/rtl/timer_watchdog.sv',
         CHECK/'ahb_protocol_checker.sv',CHECK/'axi_lite_protocol_checker.sv',HERE/'tb/bridge_tb.sv']
EXTRA_INPUTS=[HERE.parent/'local-apb-timer/run.py']
spec=importlib.util.spec_from_file_location('timer_oracle',EXTRA_INPUTS[0])
TIMER=importlib.util.module_from_spec(spec);spec.loader.exec_module(TIMER)


class Basic:
    def __init__(self,wait):self.wait=wait;self.remaining=0;self.value=0
    def step(self,rst,sel,enable,write,address,data):
        ready=int(sel and enable and self.remaining==0)
        error=int(ready and (address not in (0,4,8) or (write and address==4)))
        read={0:self.value,4:0x41504233,8:0}.get(address,0)
        if not rst:self.remaining=self.value=0
        else:
            if sel and not enable:self.remaining=self.wait
            elif sel and enable and self.remaining:self.remaining-=1
            if ready and write and not error and address==0:self.value=data
        return ready,error,read


class Model:
    def __init__(self,bus,wait):
        self.bus=bus;self.wait=wait;self.time=0;self.basic=Basic(wait);self.timer=TIMER.Oracle(4,wait);self.reset_front()
    def reset_front(self):
        self.transaction=None;self.response=None;self.last_address=self.last_write=self.last_data=0
        self.return_data=self.return_error=0
        self.active=self.launched=self.error_second=0;self.haddress=0;self.hwrite=0;self.hsize=2
        self.aw_full=self.w_full=self.ar_full=self.wi=self.ri=self.owner=self.bv=self.rv=0
        self.awa=self.ara=self.wdata=self.wstrb=self.bp=self.rp=self.rdata=0
    def preview(self,rst):
        selected=0;enable=0
        if rst and self.transaction:
            selected=1<<((self.last_address>>8)&1)
            enable=int(self.time>=self.transaction['accepted']+2)
        core=dict(ready=int(rst and self.transaction is None and self.response is None),valid=int(self.response is not None),
            error=self.return_error,data=self.return_data,sel=selected,enable=enable,write=self.last_write,
            address=self.last_address&255,wdata=self.last_data)
        return core
    def step(self,inputs):
        rst,hs,ht,ha,hw,hsize,hd,av,aa,wv,wd,ws,arv,ara,br,rr=inputs
        if not rst:self.reset_front()
        core=self.preview(rst)
        if self.bus==0:
            hr=int(not self.active or (core['valid'] and (not core['error'] or self.error_second)))
            hp=int(bool(self.active and core['valid'] and core['error']))
            outputs=[hr,hp,core['data'],0,0,0,0,0,0,0,0]
            req=dict(valid=self.active and not self.launched,write=self.hwrite,address=self.haddress,data=hd,
                     bad=self.hsize!=2,noop=False)
            consume=self.active and hr
        else:
            choose_write=self.aw_full and self.w_full and not self.wi and not self.bv
            choose_read=self.ar_full and not self.ri and not self.rv and not choose_write
            outputs=[1,0,0,int(rst and not self.aw_full and not self.wi and not self.bv),
                int(rst and not self.w_full and not self.wi and not self.bv),int(rst and not self.ar_full and not self.ri and not self.rv),
                self.bv,self.bp,self.rv,self.rdata,self.rp]
            req=dict(valid=choose_write or choose_read,write=bool(choose_write),address=self.awa if choose_write else self.ara,
                     data=self.wdata,bad=bool(choose_write and self.wstrb not in (0,15)),noop=bool(choose_write and self.wstrb==0))
            consume=not (self.bv if self.owner else self.rv)
        basic=self.basic.step(rst,core['sel']&1,core['enable'],core['write'],core['address'],core['wdata'])
        timer=self.timer.step([rst,int(bool(core['sel']&2)),core['enable'],core['write'],core['address'],core['wdata']])
        ready,error,read=(timer[6],timer[7],timer[8]) if core['sel']&2 else basic
        apb=[core['sel'],core['enable'],core['write'],core['address'],core['wdata'],ready,error,read]
        old_active,old_write=self.active,self.hwrite
        req_hs=req['valid'] and core['ready']
        if rst:
            if core['valid'] and consume:self.response=None
            if self.transaction and core['enable'] and ready:
                self.response=True;self.transaction=None;self.return_error=error;self.return_data=0 if core['write'] else read
            if req_hs:
                self.last_address=req['address'];self.last_write=int(req['write']);self.last_data=req['data']
                if req['address']&0x200 or req['address']%4 or req['bad'] or req['noop']:
                    self.response=True;self.return_error=int(bool(req['address']&0x200 or req['address']%4 or req['bad']));self.return_data=0
                else:self.transaction=dict(accepted=self.time)
            if self.bus==0:
                if req_hs:self.launched=1
                if self.active and core['valid'] and core['error'] and not self.error_second:self.error_second=1
                if self.active and outputs[0]:self.active=self.launched=self.error_second=0
                if outputs[0] and hs and ht>=2:
                    self.active=1;self.haddress=ha;self.hwrite=hw;self.hsize=hsize;self.launched=self.error_second=0
            else:
                if av and outputs[3]:self.aw_full=1;self.awa=aa
                if wv and outputs[4]:self.w_full=1;self.wdata=wd;self.wstrb=ws
                if arv and outputs[5]:self.ar_full=1;self.ara=ara
                if self.bv and br:self.bv=0
                if self.rv and rr:self.rv=0
                if req_hs:
                    self.owner=int(req['write'])
                    if req['write']:self.aw_full=self.w_full=0;self.wi=1
                    else:self.ar_full=0;self.ri=1
                if core['valid'] and consume:
                    if self.owner:self.bv=1;self.bp=2 if core['error'] else 0;self.wi=0
                    else:self.rv=1;self.rp=2 if core['error'] else 0;self.rdata=core['data'];self.ri=0
        post=[self.basic.value,timer[9],timer[10],timer[12],timer[13],timer[14],timer[15],timer[16],timer[17]]
        self.time+=1
        return [*inputs,*outputs,*apb,*post,old_active,old_write]


class Plan:
    def __init__(self,bus,wait):self.bus=bus;self.model=Model(bus,wait);self.rows=[]
    def cycle(self,rst=1,hs=0,ht=0,ha=0,hw=0,size=2,hd=0,av=0,aa=0,wv=0,wd=0xdeadbeef,ws=15,arv=0,ara=0,br=0,rr=0):
        row=self.model.step([rst,hs,ht,ha,hw,size,hd,av,aa,wv,wd,ws,arv,ara,br,rr]);self.rows.append(row);return row
    def idle(self,n=1):
        for _ in range(n):self.cycle()
    def overlap(self):
        if self.bus==0:
            self.cycle(hs=1,ht=2,ha=0,hw=1)
            for _ in range(100):
                row=self.cycle(hs=1,ht=2,ha=0,hd=0x96a55a69)
                if row[16]:break
            else:raise ValueError('AHB overlap write did not complete')
            for _ in range(100):
                if self.cycle()[16]:break
            else:raise ValueError('AHB overlap read did not complete')
        else:
            self.cycle(av=1,aa=0,wv=1,wd=0x96a55a69,arv=1,ara=0)
            for _ in range(100):
                if self.model.bv and self.model.rv:break
                self.cycle()
            else:raise ValueError('AXI overlap responses did not arrive')
            self.cycle(br=1,rr=1)
        self.idle()

    def transfer(self,address,write=False,data=0,mask=15,order=0,stall=0,abort=-1,size=2):
        if self.bus==0:
            self.cycle(hs=1,ht=2,ha=address,hw=int(write),size=size)
            for tick in range(100):
                if tick==abort:self.cycle(rst=0);self.idle();return
                row=self.cycle(hd=data)
                if row[16]:return
        else:
            aw_done=w_done=ar_done=False;blocked=0
            for tick in range(100):
                if tick==abort:self.cycle(rst=0);self.idle();return
                pre=self.model.preview(1)
                response=self.model.bv if write else self.model.rv
                accept_response=int(stall==0 or (response and blocked>=stall))
                row=self.cycle(av=int(write and not aw_done and (order!=1 or tick>=3)),aa=address,
                    wv=int(write and not w_done and (order!=0 or tick>=3)),wd=data if not w_done else data^0xffffffff,ws=mask,
                    arv=int(not write and not ar_done),ara=address,br=accept_response if write else 0,rr=accept_response if not write else 0)
                aw_done|=bool(row[7] and row[19]);w_done|=bool(row[9] and row[20]);ar_done|=bool(row[12] and row[21])
                if response and not accept_response:blocked+=1
                if (write and row[22] and row[14]) or (not write and row[24] and row[15]):return
        raise ValueError('bridge plan did not complete')


def boundary_vectors(bus,wait):
    p=Plan(bus,wait);p.cycle(rst=0);p.idle()
    for v in (0,0xffffffff,0x55555555):p.transfer(0,True,v);p.transfer(0)
    p.overlap();p.transfer(4);p.transfer(0x104);p.transfer(0x108)
    p.transfer(4,True,1);p.transfer(0x120);p.transfer(0x200)
    p.transfer(0,True,0xdeadbeef,mask=5,size=0)
    if bus==1:p.transfer(0,True,0xffffffff,mask=0);p.transfer(0)
    for address,data in [(0x104,3),(0x108,5),(0x10c,3),(0x100,5)]:p.transfer(address,True,data)
    p.idle(20);p.transfer(0x110);p.transfer(0x114);p.transfer(0x118)
    p.transfer(0x100,True,8);p.transfer(0x110);p.transfer(0x10c,True,8)
    p.transfer(0,True,0xa5a55a5a,stall=5);p.transfer(0,stall=5)
    for phase in (0,2,4):
        p.transfer(0,True,0xdeadbeef,abort=phase);p.transfer(0,True,0x12345678);p.transfer(0)
    p.cycle(rst=0);p.idle(2);return p.rows


def random_vectors(bus,wait,seed,iterations):
    rng=random.Random(seed);p=Plan(bus,wait);p.cycle(rst=0)
    for _ in range(iterations):
        address=rng.choice((0,4,8,0x100,0x104,0x108,0x10c,0x110,0x11c,0x200,3))
        p.transfer(address,bool(rng.randrange(2)),rng.choice((0,1,3,5,8,15,rng.getrandbits(32))),
                   mask=rng.choice((0,5,15)),order=rng.randrange(3),stall=rng.randrange(6),
                   abort=rng.choice((-1,-1,-1,0,2)),size=rng.choice((0,2,2,2)))
    p.transfer(0,True,0x96a55a69);p.transfer(0);p.cycle(rst=0);p.idle(2);return p.rows


def counts(rows,bus):
    return dict(reads=sum(bool(r[0] and ((r[44] and r[16] and not r[45]) if bus==0 else (r[24] and r[15]))) for r in rows),
                writes=sum(bool(r[0] and ((r[44] and r[16] and r[45]) if bus==0 else (r[22] and r[14]))) for r in rows),
                apb=sum(bool(r[0] and r[27] and r[28] and r[32]) for r in rows),
                expiries=sum(r[40] for r in rows),watchdogs=sum(r[39] for r in rows))


def make_cases(args,parameters):
    bus,wait=parameters['BUS'],parameters['WAIT_CYCLES'];baseline=boundary_vectors(bus,wait)
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=random_vectors(bus,wait,seed,args.iterations),
                           mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'BRIDGE_APB'),(2,'BRIDGE_RESPONSE'),(3,'BRIDGE_APB'),(4,'BRIDGE_APB')):
        result.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in result:c['counts']=counts(c['vectors'],bus)
    return result

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))
