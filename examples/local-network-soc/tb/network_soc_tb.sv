`timescale 1ns/1ps
module network_soc_tb;
    parameter MAX_FRAME=128,WAIT_CYCLES=0,MUTATION=0;
    reg clk=0,rst_n=0,rx_valid=0,rx_last=0,rx_error=0,tx_ready=0;
    reg [7:0] rx_data=0;reg [4:0] memory_allow=0;reg read_error=0,write_error=0;
    wire tx_valid,tx_last,halted,bus_fault,irq,ret_valid;wire [7:0] tx_data;
    wire [31:0] ret_pc,ret_insn,ret_wdata,ret_mem_addr,ret_mem_data,perf_ctrl,perf_flush;wire [4:0] ret_rd;wire [1:0] ret_mem;
    network_soc #(.MAX_FRAME(MAX_FRAME),.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [7:0] expected[0:16383],admitted[0:16383];reg [15:0] lengths[0:127],admitted_lengths[0:127];reg [31:0] rom_words[0:1023],v[0:5],rng;
    reg [3:0] reasons[0:127],events_before;reg rx_checked=0;
    reg [46:0] held_ar,held_aw;reg [36:0] held_w,held_r;reg [3:0] held_b;reg [8:0] held_tx;
    reg [40:0] held_apb;reg [72:0] held_ahb;
    reg ar_hold=0,aw_hold=0,w_hold=0,r_hold=0,b_hold=0,tx_hold=0,apb_hold=0,ahb_hold=0;
    reg owned=0,early_error=0,wire_finished=0,reset_done=0;
    integer resets=0,apb_errors=0,fault,rx_base,tx_base,compare_pc,expected_cpu,expected_apb,expected_rejected,expected_full,expected_long,admitted_frames;
    integer frame_index=0,frame_offset=0,reason_index=0,compare_index=0,admitted_bytes=0;
    integer fd,rc,words=0,cycles=0,trace_fd,ram_fd,scenario,seed,checks,expected_rx,expected_tx,expected_bytes,expected_drops;
    integer rx_frames=0,tx_frames=0,tx_bytes=0,ti=0,ri=0,wb=0,wr=0,rr=0,aw_credit=0,ar_credit=0,rx_done=0,tx_done=0,cpu_checks=0,stall=0;
    string vectors,expected_path,lengths_path,rom_path,wave,trace_path,ram_path,reasons_path,admitted_path,admitted_lengths_path;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d rx=%0d tx=%0d B=%0d R=%0d",cycles,rx_frames,tx_frames,wb,rr);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected_path)||!$value$plusargs("LENGTHS=%s",lengths_path)||
           !$value$plusargs("ROM=%s",rom_path)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("TRACE=%s",trace_path)||!$value$plusargs("RAMFILE=%s",ram_path)||
           !$value$plusargs("RX_FRAMES=%d",expected_rx)||!$value$plusargs("TX_FRAMES=%d",expected_tx)||!$value$plusargs("TX_BYTES=%d",expected_bytes)||
           !$value$plusargs("DROPS=%d",expected_drops)||!$value$plusargs("SCENARIO=%d",scenario)||!$value$plusargs("SEED=%d",seed)||!$value$plusargs("CHECKS=%d",checks)||
           !$value$plusargs("REASONS=%s",reasons_path)||!$value$plusargs("REJECTED=%d",expected_rejected)||!$value$plusargs("FULL_DROPS=%d",expected_full)||!$value$plusargs("LONG_DROPS=%d",expected_long)||
           !$value$plusargs("ADMITTED=%s",admitted_path)||!$value$plusargs("ADMITTED_LENGTHS=%s",admitted_lengths_path)||!$value$plusargs("ADMITTED_FRAMES=%d",admitted_frames)||
           !$value$plusargs("FAULT=%d",fault)||!$value$plusargs("RX_BASE=%d",rx_base)||!$value$plusargs("TX_BASE=%d",tx_base)||!$value$plusargs("COMPARE_PC=%d",compare_pc)||!$value$plusargs("CPU_CHECKS=%d",expected_cpu)||!$value$plusargs("APB_ERRORS=%d",expected_apb))$fatal(1,"arguments required");
        if(expected_tx>0)begin $readmemh(expected_path,expected,0,expected_bytes-1);$readmemh(lengths_path,lengths,0,expected_tx-1);end
        if(expected_rejected>128 || admitted_frames>128)$fatal(1,"capacity exceeded");
        if(expected_rejected>0)$readmemh(reasons_path,reasons,0,expected_rejected-1);
        if(admitted_frames>0)begin
            $readmemh(admitted_lengths_path,admitted_lengths,0,admitted_frames-1);
            for(integer j=0;j<admitted_frames;j=j+1)admitted_bytes=admitted_bytes+int'(admitted_lengths[j]);
            $readmemh(admitted_path,admitted,0,admitted_bytes-1);
        end
        #1;for(integer j=0;j<1024;j=j+1)begin dut.memory.rom[j]=32'h13;rom_words[j]=32'h13;end
        fd=$fopen(rom_path,"r");if(!fd)$fatal(1,"ROM missing");
        while(!$feof(fd))begin rc=$fscanf(fd,"%h\n",rom_words[words]);if(rc!=1||words>=1024)$fatal(1,"bad ROM");dut.memory.rom[words]=rom_words[words];words=words+1;end
        $fclose(fd);fd=$fopen(vectors,"r");trace_fd=$fopen(trace_path,"w");ram_fd=$fopen(ram_path,"w");if(!fd||!trace_fd||!ram_fd)$fatal(1,"files missing");
        $dumpfile(wave);$dumpvars(1,network_soc_tb);rng=32'(seed)|1;repeat(4)@(negedge clk);rst_n=1;
        while(!halted)begin
            if(!reset_done && ((scenario==3 && dut.wvalid)||(scenario==4 && dut.arvalid)||(scenario==5 && tx_valid)))begin
                rst_n=0;rx_valid=0;tx_ready=0;memory_allow=0;
                $display("COVER reset/global");resets=resets+1;reset_done=1;
                rx_frames=0;tx_frames=0;tx_bytes=0;ti=0;ri=0;wb=0;wr=0;rr=0;aw_credit=0;ar_credit=0;rx_done=0;tx_done=0;cpu_checks=0;stall=0;
                ar_hold=0;aw_hold=0;w_hold=0;r_hold=0;b_hold=0;tx_hold=0;apb_hold=0;ahb_hold=0;owned=0;early_error=0;wire_finished=0;
                frame_index=0;frame_offset=0;reason_index=0;compare_index=0;rx_checked=0;
                $fclose(fd);fd=$fopen(vectors,"r");$fclose(trace_fd);trace_fd=$fopen(trace_path,"w");$fclose(ram_fd);ram_fd=$fopen(ram_path,"w");
                repeat(3)@(negedge clk);rst_n=1;
            end
            cycles=cycles+1;if(cycles>400000)fail("NET_SOC_TIMEOUT");
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};memory_allow={rng[8:7]!=0,rng[6:5]!=0,rng[4:3]!=0,rng[2:1]!=0,rng[0]||rng[9]};
            rx_valid=0;rx_last=0;rx_error=0;
            // Frames start only after software enables RX. Once started, RX never consults readiness.
            if(dut.nic.run && !$feof(fd))begin
                rc=$fscanf(fd,"%h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5]);if(rc!=6)$fatal(1,"bad row");
                rx_valid=v[1][0];rx_data=v[2][7:0];rx_last=v[3][0];rx_error=v[4][0];
            end
            tx_ready=rng[12:11]!=0;
            if(scenario==5 && !reset_done)tx_ready=0;
            if(tx_valid && stall<7)begin tx_ready=0;stall=stall+1;end
            // FAULT<0 hits every response; otherwise only that beat of the frame answers SLVERR.
            read_error=scenario==2 && (fault<0 || rr==fault);write_error=scenario==1 && (fault<0 || wb==fault);
            #1;events_before=dut.nic.events;
            if($isunknown({halted,bus_fault,irq,tx_valid,dut.awvalid,dut.wvalid,dut.bvalid,dut.arvalid,dut.rvalid,dut.hready,dut.hresp,dut.nic.rx_owned}))fail("NET_SOC_UNKNOWN");
            if(bus_fault && scenario!=6)fail("NET_SOC_CPU_BUS");
            if(tx_hold && (!tx_valid || {tx_last,tx_data}!==held_tx))fail("NET_SOC_TX_HOLD");
            if(ar_hold && (!dut.arvalid || {dut.araddr,dut.arlen,dut.arsize,dut.arburst,dut.arid}!==held_ar))fail("NET_SOC_AXI_HOLD");
            if(aw_hold && (!dut.awvalid || {dut.awaddr,dut.awlen,dut.awsize,dut.awburst,dut.awid}!==held_aw))fail("NET_SOC_AXI_HOLD");
            if(w_hold && (!dut.wvalid || {dut.wdata,dut.wstrb,dut.wlast}!==held_w))fail("NET_SOC_AXI_HOLD");
            if(r_hold && (!dut.rvalid || {dut.rdata,dut.rid,dut.rresp,dut.rlast}!==held_r))fail("NET_SOC_AXI_HOLD");
            if(b_hold && (!dut.bvalid || {dut.bid,dut.bresp}!==held_b))fail("NET_SOC_AXI_HOLD");
            if(apb_hold && (!dut.psel || !dut.penable || {dut.paddr,dut.pwrite,dut.pwdata}!==held_apb))fail("NET_SOC_APB_HOLD");
            if(ahb_hold && {dut.haddr,dut.hwdata,dut.hwrite,dut.htrans,dut.hsize,dut.hburst}!==held_ahb)fail("NET_SOC_AHB_HOLD");
            tx_hold=tx_valid&&!tx_ready;held_tx={tx_last,tx_data};ar_hold=dut.arvalid&&!dut.arready;held_ar={dut.araddr,dut.arlen,dut.arsize,dut.arburst,dut.arid};
            aw_hold=dut.awvalid&&!dut.awready;held_aw={dut.awaddr,dut.awlen,dut.awsize,dut.awburst,dut.awid};w_hold=dut.wvalid&&!dut.wready;held_w={dut.wdata,dut.wstrb,dut.wlast};
            r_hold=dut.rvalid&&!dut.rready;held_r={dut.rdata,dut.rid,dut.rresp,dut.rlast};b_hold=dut.bvalid&&!dut.bready;held_b={dut.bid,dut.bresp};
            apb_hold=dut.psel&&dut.penable&&!dut.pready;held_apb={dut.paddr,dut.pwrite,dut.pwdata};ahb_hold=!dut.hready;held_ahb={dut.haddr,dut.hwdata,dut.hwrite,dut.htrans,dut.hsize,dut.hburst};
            if(tx_hold)$display("COVER flow/tx-hold");if(ar_hold||aw_hold||w_hold||r_hold)$display("COVER bus/axi-wait");if(apb_hold)$display("COVER bus/apb-wait");
            if(dut.psel && dut.penable && dut.pready && dut.pslverr)begin apb_errors=apb_errors+1;$display("COVER bus/apb-error");end
            if(dut.hresp && dut.hready && !early_error)fail("NET_SOC_AHB_ERROR");early_error=dut.hresp&&!dut.hready;
            if(rx_valid)begin ri=ri+1;if(rx_last)begin rx_frames=rx_frames+1;ri=0;end end
            if(dut.nic.frame_valid&&dut.nic.frame_ready&&!dut.nic.accept)begin
                if(reason_index>=expected_rejected||dut.nic.drop_reason!==reasons[reason_index])fail("NET_SOC_REASON");
                reason_index=reason_index+1;
            end
            if(dut.psel&&dut.penable&&dut.pready&&dut.pwrite&&!dut.pslverr&&dut.paddr==4&&(dut.pwdata[3:0]&dut.nic.events)!=0)$display("COVER status/event-beats-w1c");
            if(dut.psel&&dut.penable&&dut.pready&&dut.pwrite&&!dut.pslverr&&dut.paddr==4&&dut.pwdata[3]&&dut.nic.status[3])$display("COVER drop/status-w1c");
            if(irq && dut.nic.status==4'b1000 && dut.nic.mask==4'b1000)$display("COVER drop/irq");
            if(dut.awvalid&&dut.awready)begin
                if(aw_credit!=0 || dut.awaddr!=32'(rx_base)+32'(4*wr) || dut.awlen!=0 || dut.awsize!=2 || dut.awburst!=1 || dut.awid!=0)fail("NET_SOC_AXI");aw_credit=1;
            end
            if(dut.wvalid&&dut.wready)begin
                if(aw_credit!=1 || dut.wstrb!=15 || !dut.wlast || dut.wdata!=={24'd0,admitted[frame_offset+wr]})fail("NET_SOC_AXI");wr=wr+1;if(rx_base!=4096)$display("COVER config/relocated");
            end
            if(dut.bvalid&&dut.bready)begin
                if(aw_credit!=1 || dut.bid!=0 || dut.bresp!=(scenario==1 && (fault<0 || wb==fault) ? 2:0))fail("NET_SOC_AXI");aw_credit=0;wb=wb+1;
                if(dut.bresp!=0)$display("COVER error/rx-b");
                if(dut.bresp!=0 && fault>=0)$display("COVER error/rx-b-single");
            end
            if(dut.nic.status[0])begin
                if(wb!=int'(admitted_lengths[frame_index]) || aw_credit!=0)fail("NET_SOC_RX_ORDER");
                if(!rx_checked)for(integer j=0;j<wb;j=j+1)if(dut.memory.ram[(rx_base-4096)/4+j]!=={24'd0,admitted[frame_offset+j]})fail("NET_SOC_RX_RAM");
                rx_checked=1;rx_done=1;$display("COVER completion/rx-b-response");
            end
            if(dut.psel&&dut.penable&&dut.pready&&!dut.pwrite&&dut.paddr==16)begin
                if(dut.prdata!==32'(admitted_lengths[frame_index]))fail("NET_SOC_REG");
                $display("COVER reg/rx-len-read");
            end
            if(dut.nic.rx_owned)owned=1;
            if(owned && !dut.nic.rx_owned)fail("NET_SOC_OWNERSHIP");
            if(dut.psel&&dut.penable&&dut.pready&&dut.pwrite&&!dut.pslverr)begin
                if(dut.paddr==0 && dut.pwdata[2])begin
                    owned=0;wb=0;wr=0;rr=0;rx_done=0;tx_done=0;rx_checked=0;compare_index=0;
                    frame_offset=frame_offset+int'(admitted_lengths[frame_index]);frame_index=frame_index+1;$display("COVER ownership/release");
                end
                if(dut.paddr==0 && dut.pwdata[1])begin
                    wire_finished=0;
                    if(!rx_done || wb!=int'(admitted_lengths[frame_index]))fail("NET_SOC_RX_ORDER");
                    for(integer j=0;j<int'(dut.nic.tx_length);j=j+1)$fdisplay(ram_fd,"%08x",dut.memory.ram[(tx_base-4096)/4+j]);
                    $display("COVER cpu/build-and-check");
                end
                if(dut.paddr==4 && dut.pwdata[0])$display("COVER ownership/w1c-keeps-buffer");
            end
            if(dut.arvalid&&dut.arready)begin
                if(ar_credit!=0 || dut.araddr!=32'(tx_base)+32'(4*rr) || dut.arlen!=0 || dut.arsize!=2 || dut.arburst!=1 || dut.arid!=0)fail("NET_SOC_AXI");ar_credit=1;
            end
            if(dut.rvalid&&dut.rready)begin
                if(ar_credit!=1 || dut.rid!=0 || !dut.rlast || dut.rresp!=(scenario==2 && (fault<0 || rr==fault) ? 2:0))fail("NET_SOC_AXI");ar_credit=0;rr=rr+1;
                if(dut.rresp!=0)$display("COVER error/tx-r");
                if(dut.rresp!=0 && fault>=0)$display("COVER error/tx-r-single");
            end
            if(dut.nic.status[1])begin if(!wire_finished || ti!=0)fail("NET_SOC_TX_ORDER");tx_done=tx_frames;$display("COVER completion/wire-last");end
            if(tx_valid)begin
                if(tx_frames>=expected_tx || tx_bytes>=expected_bytes || tx_data!==expected[tx_bytes] || tx_last!==(ti==int'(lengths[tx_frames])-1))fail("NET_SOC_FRAME");
                if(tx_ready)begin tx_bytes=tx_bytes+1;ti=ti+1;if(tx_last)begin tx_frames=tx_frames+1;ti=0;wire_finished=1;$display("COVER reply/packet");end end
            end
            if(ret_valid)begin
                if(ret_pc[1:0]!=0 || ret_pc>=32'h800 || ret_insn!==rom_words[ret_pc>>2])fail("NET_SOC_ROM");
                $fdisplay(trace_fd,"%08x %08x rd=%0d value=%08x mem=%0d addr=%08x data=%08x",ret_pc,ret_insn,ret_rd,ret_wdata,ret_mem,ret_mem_addr,ret_mem_data);
                // The word after the label reads the TX buffer; other TX reads belong to the checksums and CRC.
                if(ret_pc==compare_pc+4)begin
                    if(ret_mem!=1 || ret_mem_addr!=32'(tx_base)+32'(4*compare_index))fail("NET_SOC_CPU_CHECKS");
                    compare_index=compare_index+1;cpu_checks=cpu_checks+1;
                end
                if(dut.cpu_write && dut.cpu_be!=15)fail("NET_SOC_CPU_BUS");
            end
            @(posedge clk);#1;
            if((dut.nic.status&events_before)!==events_before)fail("NET_SOC_STATUS");
            @(negedge clk);
        end
        if(!$feof(fd) || rx_frames!=expected_rx || tx_frames!=expected_tx || tx_bytes!=expected_bytes || dut.nic.drop_count!=expected_drops ||
           ti!=0 || ri!=0 || aw_credit!=0 || ar_credit!=0 || dut.memory.ram[1023]!==32'h600d600d || dut.nic.rx_owned || tx_valid)fail("NET_SOC_COMPLETION");
        if(apb_errors!=expected_apb || bus_fault!==(scenario==6))fail("NET_SOC_APB_ERROR");
        if(cpu_checks!=expected_cpu)fail("NET_SOC_CPU_CHECKS");
        if(dut.nic.full_drops!=expected_full || dut.nic.long_drops!=expected_long || dut.nic.rejected!=expected_rejected || reason_index!=expected_rejected)fail("NET_SOC_DROP_COUNT");
        if(expected_drops>0)$display("COVER drop/packet");
        $display("COUNT rx_frames=%0d",rx_frames);$display("COUNT tx_frames=%0d",tx_frames);$display("COUNT tx_bytes=%0d",tx_bytes);$display("COUNT drops=%0d",expected_drops);$display("COUNT resets=%0d",resets);
        if(resets!=((scenario>=3 && scenario<=5) ? 1:0))fail("NET_SOC_COMPLETION");
        if(checks!=1+tx_bytes)fail("NET_SOC_COMPLETION");$display("RESULT PASS checks=%0d",checks);$fclose(fd);$fclose(trace_fd);$fclose(ram_fd);$finish;
    end
endmodule
