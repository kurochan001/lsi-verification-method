`timescale 1ns/1ps
module tmr_tb;
    parameter WIDTH=8,MUTATION=0;
    reg clk=0,rst_n=0,write_en=0,repair_en=0;
    reg [WIDTH-1:0] write_data=0,fault0=0,fault1=0,fault2=0;
    wire [WIDTH-1:0] voted;wire disagreement,repair_attempt;
    tmr_register #(.WIDTH(WIDTH),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [31:0] v[0:6],e[0:5];integer fd,ef,n,rc,checks,rows=0,injections=0,resets=0;reg old_rst=0,old_bad;reg [WIDTH-1:0] old_vote;
    string vectors,expected,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d",rows);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("CHECKS=%d",checks))$fatal(1,"arguments required");
        fd=$fopen(vectors,"r");ef=$fopen(expected,"r");if(!fd||!ef)$fatal(1,"inputs missing");$dumpfile(wave);$dumpvars(2,tmr_tb);
        @(negedge clk);
        while(!$feof(fd))begin
            for(integer j=0;j<7;j=j+1)begin rc=$fscanf(fd,"%h\n",v[j]);if(rc!=1)$fatal(1,"bad input");end
            
            for(integer j=0;j<6;j=j+1)begin rc=$fscanf(ef,"%h\n",e[j]);if(rc!=1)$fatal(1,"bad oracle");end
            
            rst_n=v[0][0];write_en=v[1][0];write_data=WIDTH'(v[2]);repair_en=v[3][0];fault0=WIDTH'(v[4]);fault1=WIDTH'(v[5]);fault2=WIDTH'(v[6]);
            if(old_rst&&!rst_n)begin resets=resets+1;$display("COVER reset/active");end old_rst=rst_n;
            old_bad=disagreement;old_vote=voted;
            if(rst_n && |{fault0,fault1,fault2})begin
                injections=injections+1;
                if(fault0!=0)$display("COVER fault/lane0");if(fault1!=0)$display("COVER fault/lane1");if(fault2!=0)$display("COVER fault/lane2");
                if((fault0!=0)+(fault1!=0)+(fault2!=0)>=2)$display("COVER limit/multiple-lanes");
            end
            @(posedge clk);#1;rows=rows+1;
            if(voted!==WIDTH'(e[0]))fail("TMR_VOTE");
            if({disagreement,repair_attempt}!=={e[1][0],e[2][0]})fail("TMR_STATUS");
            if(dut.q0!==WIDTH'(e[3]) || dut.q1!==WIDTH'(e[4]) || dut.q2!==WIDTH'(e[5]))fail("TMR_STATE");
            if(rst_n && fault0==fault1 && fault1==fault2 && fault0!=0 && !disagreement && voted!=old_vote)$display("COVER limit/common-cause");
            if(rst_n && fault0!=0 && fault0==fault1 && fault2==0 && voted==dut.q0 && voted!=dut.q2)$display("COVER limit/wrong-majority");
            if(rst_n&&repair_attempt)$display("COVER repair/attempt");
            if(rst_n&&old_bad&&write_en&&repair_en)$display("COVER repair/write-priority");
            if(rst_n&&old_bad&&!repair_en&&!write_en)$display("COVER repair/disabled");
            if(rst_n&&write_en)$display("COVER normal/write");
            @(negedge clk);
        end
        if(!$feof(ef))fail("TMR_COMPLETION");
        $display("COUNT rows=%0d",rows);$display("COUNT injections=%0d",injections);$display("COUNT resets=%0d",resets);
        if(rows!=checks)fail("TMR_COMPLETION");$display("RESULT PASS checks=%0d",rows);$fclose(fd);$fclose(ef);$finish;
    end
endmodule
