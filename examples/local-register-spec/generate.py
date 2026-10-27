#!/usr/bin/env python3
"""Generate a deliberately limited APB/C/UVM view from elaborated SystemRDL."""
import argparse,json
from pathlib import Path
from systemrdl import RDLCompiler

def model(path):
    c=RDLCompiler();c.compile_file(str(path));top=c.elaborate().top;registers=[]
    if top.list_properties() or any(type(node).__name__!='RegNode' for node in top.children()):raise ValueError('only a flat address map without additional properties supported')
    for reg in top.registers():
        fields=list(reg.fields())
        if set(reg.list_properties())-{'regwidth'} or reg.is_array or reg.get_property('regwidth')!=32 or len(fields)!=1:raise ValueError('only scalar 32-bit one-field registers supported')
        f=fields[0];sw=f.get_property('sw').name;ow=f.get_property('onwrite');ow=ow.name if ow else None
        if set(f.list_properties())-{'sw','hw','reset','onwrite'} or f.get_property('hw').name!=('w' if reg.inst_name=='pending' else 'r'):raise ValueError('unsupported hardware update or field property')
        if f.low!=0 or not 1<=f.width<=32 or sw not in ('r','rw') or ow not in (None,'woclr') or f.get_property('onread') is not None:raise ValueError('unsupported field semantics')
        reset=f.get_property('reset')
        if not isinstance(reset,int) or reg.absolute_address%4 or reg.absolute_address>252:raise ValueError('explicit integer reset and aligned byte offset required')
        registers.append(dict(name=reg.inst_name,address=reg.absolute_address,width=f.width,reset=reset,access='RO' if sw=='r' else 'W1C' if ow=='woclr' else 'RW'))
    if {r['name'] for r in registers}!={'cfg','idreg','pending'}:raise ValueError('this teaching exporter expects cfg/idreg/pending')
    if next(r for r in registers if r['name']=='pending')['width']>4:raise ValueError('hardware event port is four bits')
    return registers

def export(registers,out):
    out.mkdir(parents=True,exist_ok=False);(out/'model.json').write_text(json.dumps(registers,indent=2)+'\n')
    decl=[];reset=[];reads=[];writes=[];invalid=[];header=['#ifndef DEMO_REGS_H','#define DEMO_REGS_H'];ral=[]
    for r in registers:
        n=r['name'];w=r['width'];a=r['address'];value=r['reset'];access=r['access'];mask=(1<<w)-1
        decl.append(f'reg [{w-1}:0] {n};');reset.append(f"{n}<=32'h{value:x}"+(' ^ (MUTATION==1 ? 1:0);' if n=='cfg' else ';'))
        reads.append(f"8'd{a}:prdata={n};");invalid.append(f"paddr==8'd{a}")
        if access=='RW':writes.append(f"if(done && !bad && pwrite && paddr==8'd{a}){n}<=pwdata & (MUTATION==2 ? 32'hf:32'h{mask:x});")
        elif access=='W1C':writes.append(f"{n}<=MUTATION==3 && done && pwrite && paddr==8'd{a} ? ({n}|events)&~pwdata[{w-1}:0]:({n}&~((done && !bad && pwrite && paddr==8'd{a}) ? pwdata[{w-1}:0]:{w}'b0))|events[{w-1}:0];")
        header += [f'#define DEMO_{n.upper()}_ADDR {a}u',f'#define DEMO_{n.upper()}_MASK 0x{mask:x}u',f'#define DEMO_{n.upper()}_RESET 0x{value:x}u']
        ral.append(f'''{n}=rdl_word::type_id::create("{n}");{n}.configure(this);{n}.build("{access}",{w},32'h{value:x});default_map.add_reg({n},{a},"{'RO' if access=='RO' else 'RW'}");''')
    ro=' || '.join(f"paddr==8'd{r['address']}" for r in registers if r['access']=='RO') or "1'b0"
    text='''module rdl_regs #(parameter MUTATION=0,WAIT_CYCLES=0)(input wire clk,rst_n,psel,penable,pwrite,input wire[7:0]paddr,input wire[31:0]pwdata,input wire[3:0]events,output wire pready,pslverr,output reg[31:0]prdata);
'''+ '\n'.join(decl)+f'''
integer remaining;wire done=psel && penable && pready;
wire bad=!({' || '.join(invalid)}) || (pwrite && ({ro}));
assign pready=psel && penable && remaining==0;assign pslverr=done && bad;
always @*begin prdata=0;case(paddr){''.join(reads)}default:;endcase end
always @(posedge clk)begin
if(!rst_n)begin remaining<=0;{''.join(reset)}end
else begin
if(psel && !penable)remaining<=WAIT_CYCLES;else if(psel && penable && remaining>0)remaining<=remaining-1;
{''.join(writes)}
end end endmodule
'''
    (out/'rdl_regs.sv').write_text(text);(out/'demo_regs.h').write_text('\n'.join(header+['#endif'])+'\n')
    (out/'rdl_pkg.sv').write_text('''`include "uvm_macros.svh"
package rdl_pkg;import uvm_pkg::*;
class rdl_word extends uvm_reg;
`uvm_object_utils(rdl_word)
uvm_reg_field value;
function new(string n="rdl_word");super.new(n,32,UVM_NO_COVERAGE);endfunction
function void build(string access,int width,uvm_reg_data_t reset_value);
value=uvm_reg_field::type_id::create("value");value.configure(this,width,0,access,0,reset_value,1,0,0);
endfunction endclass
class rdl_block extends uvm_reg_block;
`uvm_object_utils(rdl_block)
rdl_word cfg,idreg,pending;
function new(string n="rdl_block");super.new(n,UVM_NO_COVERAGE);endfunction
function void build();default_map=create_map("map",0,4,UVM_LITTLE_ENDIAN);
'''+''.join(ral)+'''lock_model();endfunction endclass
endpackage
''')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args();export(model(a.source),a.out)
if __name__=='__main__':main()
