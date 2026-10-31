from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]


def vectors(count,reset_busy=False):
    rows=[];remaining=0;valid=0;match=0;mask=(1<<(count*8))-1
    def cycle(rst=1,start=0,ready=1,key=0,guess=0):
        nonlocal remaining,valid,match
        if not rst:remaining=valid=match=0
        accept=int(bool(rst and not remaining and not valid));busy=int(remaining>0)
        rows.append([rst,start,ready,key,guess,accept,busy,valid,match,(busy<<1)|valid])
        if rst:
            if valid and ready:valid=0
            if remaining:
                remaining-=1
                if not remaining:valid=1
            if start and accept:remaining=count;match=int(key==guess)
    cycle(rst=0)
    if reset_busy:
        cycle(start=1,key=mask,guess=mask);cycle(ready=0);cycle(rst=0)
    rng=random.Random(17)
    for _ in range(4):
        key=rng.getrandbits(count*8)|1
        for position in [-1,*range(count)]:
            guess=key if position==-1 else key^(1<<(8*position))
            cycle(start=1,key=key,guess=guess)
            for _ in range(count):cycle(start=1,key=(~key)&mask,guess=(~guess)&mask)
            cycle(ready=0);cycle(ready=0);cycle();cycle()
    return rows


def simulate(count,mutation=0,reset_busy=False):
    if not (shutil.which('iverilog') and shutil.which('vvp')):raise unittest.SkipTest('Icarus required')
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);tb=out/'tb.sv';vec=out/'vectors.txt'
        vec.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in vectors(count,reset_busy)))
        tb.write_text('''`timescale 1ns/1ps
module ct_tb;
 parameter BYTES=2,MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start=0,result_ready=0;
 reg [8*BYTES-1:0] secret=0,guess=0;
 wire ready,busy,result_valid,match;wire [2:0] public_status;
 constant_time_compare #(.BYTES(BYTES),.MUTATION(MUTATION)) dut(.*);
 reg [63:0] v[0:9];integer fd,n,checks=0;string path;
 task fail(input string s);begin $display("CHECK_FAIL %s",s);$fatal(1,"step=%0d",checks);end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",path))$fatal(1,"input required");
 fd=$fopen(path,"r");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h\\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9]);if(n!=10)$fatal(1,"row");
 rst_n=v[0][0];start=v[1][0];result_ready=v[2][0];secret=v[3][8*BYTES-1:0];guess=v[4][8*BYTES-1:0];#1;
 if({ready,busy,result_valid}!=={v[5][0],v[6][0],v[7][0]})fail("CT_TIME");
 if(public_status!==v[9][2:0])fail("CT_PUBLIC");
 if(result_valid && match!==v[8][0])fail("CT_RESULT");
 if(!busy && (dut.secret_work!==0 || dut.guess_work!==0))fail("CT_ERASE");
 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
''')
        build=subprocess.run(['iverilog','-g2012','-s','ct_tb',f'-Pct_tb.BYTES={count}',f'-Pct_tb.MUTATION={mutation}',
                              '-o',str(out/'sim'),str(HERE/'rtl/constant_time_compare.sv'),str(tb)],capture_output=True,text=True,timeout=30)
        if build.returncode:raise AssertionError(build.stderr)
        return subprocess.run(['vvp',str(out/'sim'),f'+VECTORS={vec}'],capture_output=True,text=True,timeout=30)


class ComparisonTests(unittest.TestCase):
    def test_equal_and_every_mismatch_position_have_fixed_latency(self):
        for count in (2,4):
            result=simulate(count);self.assertEqual(result.returncode,0,result.stdout)

    def test_reset_cancels_and_erases_pending_comparison(self):
        for count in (2,4):
            result=simulate(count,reset_busy=True);self.assertEqual(result.returncode,0,result.stdout)

    def test_early_exit_is_detected(self):
        result=simulate(4,1);self.assertNotEqual(result.returncode,0);self.assertIn('CT_TIME',result.stdout)

    def test_public_secret_bit_is_detected(self):
        result=simulate(4,2);self.assertNotEqual(result.returncode,0);self.assertIn('CT_PUBLIC',result.stdout)

    def test_uncompared_last_byte_is_detected(self):
        result=simulate(4,3);self.assertNotEqual(result.returncode,0);self.assertIn('CT_RESULT',result.stdout)

    def test_secret_input_changes_cannot_replace_captured_secret(self):
        result=simulate(4,4);self.assertNotEqual(result.returncode,0);self.assertIn('CT_RESULT',result.stdout)


if __name__=='__main__':unittest.main()
