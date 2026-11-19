`timescale 1ns/1ps
module sync_ram_fifo_tb;
    parameter integer WIDTH=32, DEPTH=4, READ_LATENCY=1, MUTATION=0;
    parameter integer WR_PERIOD=10, RD_PERIOD=17, RD_PHASE=3;
    localparam integer PW=$clog2(DEPTH)+1;
    reg wr_clk=0,rd_clk=0,arst_n=0;
    initial forever #(WR_PERIOD/2.0)wr_clk=~wr_clk;
    initial begin #(RD_PHASE);forever #(RD_PERIOD/2.0)rd_clk=~rd_clk;end
    reg wr_valid=0,rd_ready=0;
    reg [WIDTH-1:0] wr_data=0;
    wire wr_ready,rd_valid;
    wire [WIDTH-1:0] rd_data;
    sync_ram_async_fifo #(.WIDTH(WIDTH),.DEPTH(DEPTH),.READ_LATENCY(READ_LATENCY),.MUTATION(MUTATION)) dut(.*);
    reg [WIDTH-1:0] accepted[0:4095];
    integer written=0,read_count=0,generation=0,rd_cycles=0,checks,seed,fd;
    integer stalls=0,full_hits=0,empty_hits=0;
    reg wr_taken=0,wr_stalled=0,rd_stalled=0;
    reg [WIDTH-1:0] wr_held=0,rd_held=0;
    reg [31:0] source_rng,sink_rng;
    reg [PW-1:0] old_wgray=0,old_rgray=0;
    string wave,csv,test_name;

    function automatic [31:0] advance(input [31:0] value);
        reg [31:0] x;
        begin x=value^(value<<13);x=x^(x>>17);advance=x^(x<<5);end
    endfunction
    function automatic [WIDTH-1:0] word(input integer epoch,index);
        word=WIDTH'((epoch*73)^(index*131+17));
    endfunction
    task fail(input string reason);
        $display("CHECK_FAIL SYNC_RAM_FIFO");
        $fatal(1,"case=%s seed=%0d generation=%0d index=%0d expected=%h actual=%h clocks=%0d/%0d phase=%0d depth=%0d latency=%0d written=%0d read=%0d reason=%s",
            test_name,seed,generation,read_count,accepted[read_count],rd_data,WR_PERIOD,RD_PERIOD,RD_PHASE,DEPTH,READ_LATENCY,written,read_count,reason);
    endtask

    always @(negedge wr_clk)begin
        if(!arst_n)begin wr_valid<=0;wr_data<=0;end
        else if(!(wr_valid && !wr_taken))begin
            source_rng=advance(source_rng);
            wr_valid<=written<(generation==0 ? 4*DEPTH:checks) && (generation==0 || source_rng[2:0]!=0);
            wr_data<=word(generation,written);
        end
    end
    always @(negedge rd_clk)begin
        sink_rng=advance(sink_rng);
        rd_ready<=arst_n && generation==1 && rd_cycles>80 && sink_rng[2:0]!=0 && rd_cycles%29<24;
    end
    always @(posedge wr_clk or negedge arst_n)begin
        if(!arst_n)begin written<=0;wr_taken<=0;wr_stalled<=0;old_wgray=0;end
        else begin
            if(wr_stalled && (wr_valid !== 1 || wr_data !== wr_held))fail("source changed while stalled");
            wr_taken<=wr_valid && wr_ready;
            wr_stalled<=wr_valid && !wr_ready;wr_held<=wr_data;
            if(wr_valid && wr_ready)begin accepted[written]=wr_data;written<=written+1;end
            if(wr_valid && !wr_ready && dut.full)full_hits=full_hits+1;
            #0.001;
            if($isunknown(dut.wgray) || $countones(dut.wgray^old_wgray)>1)fail("local write Gray transition");
            old_wgray=dut.wgray;
            if(written-read_count>DEPTH)fail("capacity exceeded before external consumption");
        end
    end
    always @(posedge rd_clk or negedge arst_n)begin
        if(!arst_n)begin read_count<=0;rd_cycles<=0;rd_stalled<=0;old_rgray=0;end
        else begin
            rd_cycles<=rd_cycles+1;
            if(rd_stalled && (rd_valid !== 1 || rd_data !== rd_held))fail("output changed while stalled");
            rd_stalled<=rd_valid && !rd_ready;rd_held<=rd_data;
            if(rd_valid && !rd_ready)stalls=stalls+1;
            if(!rd_valid)empty_hits=empty_hits+1;
            if(rd_valid && rd_ready)begin
                if(read_count>=written || rd_data !== accepted[read_count])fail("accepted write/read sequence differs");
                read_count<=read_count+1;
            end
            #0.001;
            if($isunknown(dut.rgray) || $countones(dut.rgray^old_rgray)>1)fail("local read Gray transition");
            old_rgray=dut.rgray;
            if(dut.count>dut.reserved || dut.reserved>READ_LATENCY+2)fail("prefetch reservation overflow");
            if(generation==1 && fd)$fdisplay(fd,"%0t,%0d,%0d,%0d,%b,%b",$time,written-read_count,dut.reserved,dut.count,rd_valid,rd_ready);
        end
    end

    initial begin
        if(!$value$plusargs("CHECKS=%d",checks)||!$value$plusargs("SEED=%d",seed)||
            !$value$plusargs("CSV=%s",csv)||!$value$plusargs("CASE=%s",test_name))$fatal(1,"arguments required");
        if($value$plusargs("WAVE=%s",wave))begin $dumpfile(wave);$dumpvars(0,sync_ram_fifo_tb);end
        source_rng=32'(seed)^32'h12345;sink_rng=32'(seed)^32'habcd;
        fd=$fopen(csv,"w");$fdisplay(fd,"time_ps,ideal_occupancy,reserved,queued,valid,ready");
        repeat(6)@(negedge wr_clk);arst_n=1;
        wait(written==DEPTH && !wr_ready);#1;
        $display("COVER fifo/full");$display("COVER reset/pending");
        arst_n=0;generation=1;
        repeat(6)@(negedge wr_clk);arst_n=1;
        wait(read_count==checks);
        repeat(12)@(negedge rd_clk);
        if(written!=checks || read_count!=checks || rd_valid !== 0 || !stalls || !full_hits || !empty_hits)
            fail("missing completion or boundary observation");
        $display("COVER fifo/empty");$display("COVER flow/stall");$display("COVER flow/resume");
        $display("COVER pointer/wrap");$display("COVER reset/new-generation");$display("COVER ram/prefetch");
        $fclose(fd);$display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
    initial begin #1000000;fail("timeout");end
endmodule
