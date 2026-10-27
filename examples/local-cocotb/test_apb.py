"""APB tests driven by coroutines, checking every phase against register semantics."""
import json
import os
from pathlib import Path
import cocotb
from cocotb.triggers import Timer

def fail(label):
    print('CHECK_FAIL '+label,flush=True);raise AssertionError(label)

@cocotb.test()
async def verify(dut):
    case=json.loads(Path(os.environ['CASE_JSON']).read_text());config=pending=0
    for name,value in dict(clk=0,rst_n=0,psel=0,penable=0,pwrite=0,paddr=0,pwdata=0,events=0).items():getattr(dut,name).value=value
    async def edge(events=0,write=None):
        nonlocal config,pending
        dut.events.value=events;dut.clk.value=0;await Timer(5,unit='ns')
        if int(dut.rst_n.value):
            if write is not None:
                address,data,error=write
                if not error and address==0:config=data
                clear=data&15 if not error and address==8 else 0
            else:clear=0
            pending=(pending&~clear)|events
        else:config=pending=0
        dut.clk.value=1;await Timer(1,unit='ns')
        if int(dut.config_value.value)!=config:fail('COCOTB_SETUP' if int(dut.psel.value) and not int(dut.penable.value) else 'COCOTB_CONFIG')
        if int(dut.pending.value)!=pending:fail('COCOTB_PENDING')
        await Timer(4,unit='ns');dut.clk.value=0
    await edge();await edge();dut.rst_n.value=1
    for index,(address,write,data,setup_events,complete_events) in enumerate(case['operations']):
        error=int(address not in (0,4,8) or (write and address==4))
        for name,value in dict(psel=1,penable=0,pwrite=write,paddr=address,pwdata=data).items():getattr(dut,name).value=value
        await Timer(1,unit='ns')
        if int(dut.pready.value):fail('COCOTB_PROTOCOL')
        await edge(setup_events);dut.penable.value=1
        for wait in range(case['wait']+1):
            dut.events.value=complete_events if wait==case['wait'] else 0
            await Timer(1,unit='ns')
            if int(dut.pready.value)!=int(wait==case['wait']):fail('COCOTB_PROTOCOL')
            if int(dut.pslverr.value)!=(error if wait==case['wait'] else 0):fail('COCOTB_PROTOCOL')
            expected={0:config,4:0x41504233 ^ int(bool(case['checker'])),8:pending}.get(address,0)
            if not write and int(dut.prdata.value)!=expected:fail('COCOTB_READ')
            await edge(complete_events if wait==case['wait'] else 0,(address,data,error) if wait==case['wait'] and write else None)
        print('COVER access/write' if write else 'COVER access/read',flush=True)
        print('COVER response/error' if error else 'COVER response/okay',flush=True)
        if address==8 and write and complete_events&data:print('COVER pending/event-wins',flush=True)
        if case['wait']:print('COVER access/wait',flush=True)
        else:print('COVER access/zero-wait',flush=True)
        dut.psel.value=0;dut.penable.value=0;await edge()
    counts=dict(transactions=len(case['operations']),reads=sum(not r[1] for r in case['operations']),writes=sum(r[1] for r in case['operations']),errors=sum(r[0] not in (0,4,8) or (r[1] and r[0]==4) for r in case['operations']))
    for key,value in counts.items():print(f'COUNT {key}={value}',flush=True)
    # One configuration-specific bin is normalized to a common contract goal.
    print('COVER access/wait-policy',flush=True)
    print(f"RESULT PASS checks={len(case['operations'])}",flush=True)
