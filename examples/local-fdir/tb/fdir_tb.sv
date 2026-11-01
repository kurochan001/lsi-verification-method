`timescale 1ns/1ps
module fdir_tb;
    parameter DEPTH=4,WD_LIMIT=5,TRIP=3,MUTATION=0;
    reg clk=0,rst_n=0,start=0,kick=0,ack=0,recover=0,scrub_en=0,cfg_write=0,inject_en=0,maint_write=0,cmd_valid=0;
    reg [7:0] cfg_data=0,fault0=0,fault1=0,fault2=0,maint_data=0,cmd_data=0,cmd_seq=0;
    reg [$clog2(DEPTH)-1:0] inject_addr=0,maint_addr=0,cmd_addr=0;reg [12:0] inject_mask=0;reg [1:0] cmd_op=0;
    wire cmd_ready,commit,cancelled,recovered,recovery_failed,irq;wire [7:0] actuator,result,expected_seq;wire [1:0] state;wire [3:0] cause;
    fdir_node #(.DEPTH(DEPTH),.WD_LIMIT(WD_LIMIT),.TRIP(TRIP),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [31:0] v[0:21],e[0:20+DEPTH];integer fd,ef,rc,checks,rows=0,injections=0,resets=0,accepted=0,commits=0,cancels=0,recoveries=0,failures=0,rejected=0,reset_cancels=0;
    reg old_rst=0;reg [1:0] old_state;reg [3:0] event_before;
    string vectors,expected,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d state=%0d cause=%h",rows,state,cause);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("CHECKS=%d",checks))$fatal(1,"arguments required");
        fd=$fopen(vectors,"r");ef=$fopen(expected,"r");if(!fd||!ef)$fatal(1,"inputs missing");$dumpfile(wave);$dumpvars(2,fdir_tb);
        @(negedge clk);
        while(!$feof(fd))begin
            for(integer j=0;j<22;j=j+1)begin rc=$fscanf(fd,"%h\n",v[j]);if(rc!=1)$fatal(1,"bad input");end 
            for(integer j=0;j<21+DEPTH;j=j+1)begin rc=$fscanf(ef,"%h\n",e[j]);if(rc!=1)$fatal(1,"bad oracle");end 
            rst_n=v[0][0];start=v[1][0];kick=v[2][0];ack=v[3][0];recover=v[4][0];scrub_en=v[5][0];cfg_write=v[6][0];cfg_data=v[7][7:0];
            fault0=v[8][7:0];fault1=v[9][7:0];fault2=v[10][7:0];inject_en=v[11][0];inject_addr=$clog2(DEPTH)'(v[12]);inject_mask=v[13][12:0];
            maint_write=v[14][0];maint_addr=$clog2(DEPTH)'(v[15]);maint_data=v[16][7:0];cmd_valid=v[17][0];cmd_op=v[18][1:0];cmd_addr=$clog2(DEPTH)'(v[19]);cmd_data=v[20][7:0];cmd_seq=v[21][7:0];
            #1;old_state=state;event_before=dut.event_cause;
            if(old_rst&&!rst_n)begin resets=resets+1;if(dut.pending)reset_cancels=reset_cancels+1;$display("COVER reset/active");end old_rst=rst_n;
            if(rst_n)begin
                if(cmd_valid&&cmd_ready)begin accepted=accepted+1;if(cmd_op>1 || cmd_seq!=expected_seq)rejected=rejected+1;end
                if(inject_en || |{fault0,fault1,fault2})injections=injections+1;
                if(cfg_write && (state==1 || state==3))$display("COVER config/locked");
                if(dut.writing && dut.scrub_en && dut.store.scrub_c && dut.scrub_addr==dut.mem_addr)$display("COVER ecc/write-priority");
                if(state==1 && dut.watchdog_count==1 && kick)$display("COVER deadline/kick-wins");
                if(state==2 && recover && dut.mismatch)$display("COVER recovery/config-blocked");
                if(dut.mem_corrected)$display("COVER ecc/read-repair");
                if(dut.scrub_corrected)$display("COVER ecc/scrub-repair");
                if(dut.mismatch && state==1 && dut.streak<TRIP-1)$display("COVER tmr/masked");
                if(ack && dut.event_cause!=0)$display("COVER irq/event-wins");
                if(ack && state==2)$display("COVER recovery/ack-keeps-safe");
                if(maint_write && state==2)$display("COVER recovery/maintenance");
                if(dut.pending && rst_n && inject_en)$display("COVER fault/pending");
            end
            @(posedge clk);#1;rows=rows+1;
            if(commit!==e[4][0] || cancelled!==e[5][0])fail("FDIR_CONTAIN");
            if(state!==e[0][1:0] || cause!==e[1][3:0] || irq!==e[2][0])fail("FDIR_STATE");
            if(expected_seq!==e[3][7:0] || result!==e[8][7:0] || actuator!==e[9][7:0])fail("FDIR_DATA");
            if(recovered!==e[6][0] || recovery_failed!==e[7][0])fail("FDIR_RECOVERY");
            if(dut.watchdog_count!==e[10][3:0] || dut.limit_value!==e[11][7:0] || dut.mismatch!==e[12][0] || dut.scrub_addr!==$clog2(DEPTH)'(e[13]) ||
                dut.scrub_corrected!==e[14][0] || dut.scrub_uncorrectable!==e[15][0] || dut.pending!==e[16][0] || dut.streak!==int'(e[17]))fail("FDIR_INTERNAL");
            if(dut.config_bank.q0!==e[18][7:0] || dut.config_bank.q1!==e[19][7:0] || dut.config_bank.q2!==e[20][7:0])fail("FDIR_TMR");
            for(integer j=0;j<DEPTH;j=j+1)if(dut.store.memory[j]!==e[21+j][12:0])fail("FDIR_MEMORY");
            if(rst_n)begin
                if(commit)begin commits=commits+1;$display("COVER normal/commit");if(expected_seq==0)$display("COVER command/sequence-wrap");end
                if(cancelled)begin cancels=cancels+1;$display("COVER containment/cancel");end
                if(recovered)begin recoveries=recoveries+1;$display("COVER recovery/success");end
                if(recovery_failed)begin failures=failures+1;$display("COVER recovery/refused");end
                if(old_state==1 && state==2)begin
                    if((event_before[0]+event_before[1]+event_before[2]+event_before[3])>=2)$display("COVER safe/simultaneous");
                    if(event_before[0])$display("COVER safe/tmr");if(event_before[1])$display("COVER safe/ecc");
                    if(event_before[2])$display("COVER safe/watchdog");if(event_before[3])$display("COVER safe/command");
                end
            end
            @(negedge clk);
        end
        if(!$feof(ef) || dut.pending || state==3)fail("FDIR_COMPLETION");
        $display("COUNT rows=%0d",rows);$display("COUNT injections=%0d",injections);$display("COUNT resets=%0d",resets);$display("COUNT accepted=%0d",accepted);
        $display("COUNT commits=%0d",commits);$display("COUNT cancels=%0d",cancels);$display("COUNT recoveries=%0d",recoveries);$display("COUNT failures=%0d",failures);
        $display("COUNT rejected=%0d",rejected);$display("COUNT reset_cancels=%0d",reset_cancels);
        if(accepted!=commits+cancels+reset_cancels+rejected)fail("FDIR_ACCOUNTING");
        if(rows!=checks)fail("FDIR_COMPLETION");$display("RESULT PASS checks=%0d",rows);$fclose(fd);$fclose(ef);$finish;
    end
endmodule
