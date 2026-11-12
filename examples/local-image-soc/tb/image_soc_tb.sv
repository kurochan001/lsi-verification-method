`timescale 1ns/1ps
module image_soc_tb;
    parameter W=5,H=5,WAIT_CYCLES=0,MUTATION=0;
    localparam N=W*H;
    reg clk=0,rst_n=0;
    reg [4:0] memory_allow=0;
    reg read_error=0,write_error=0;
    wire halted,bus_fault,irq,busy,done,error,ret_valid;
    wire [31:0] ret_pc,ret_insn,ret_wdata,ret_mem_addr,ret_mem_data,perf_ctrl,perf_flush;
    wire [4:0] ret_rd;wire [1:0] ret_mem;
    image_soc #(.W(W),.H(H),.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [7:0] inputs[0:1023],golden[0:1023];
    reg [31:0] rom_words[0:1023],rng;
    reg [46:0] held_ar,held_aw;
    reg [36:0] held_w;
    reg [36:0] held_r;
    reg [56:0] held_apb;
    reg [72:0] held_ahb;
    reg [3:0] held_b;
    reg ar_hold=0,aw_hold=0,w_hold=0,r_hold=0,apb_hold=0,ahb_hold=0,b_hold=0;
    reg irq_old=0,reset_done=0,error_first=0,cpu_hold=0;
    integer irq_gate=0;
    reg [32:0] cpu_held;
    integer invalid_seen=0,fault,src_base,dst_base,expected_apb,expected_ahb,apb_errors=0,ahb_errors=0,b_count=0,cpu_stores=0;
    integer frames,seed,scenario,cycles=0,pixels=0,completed=0,irqs=0,cpu_checks=0;
    integer rd_pixels=0,wr_pixels=0,issued=0,addressed=0,rleft=0,wleft=0,bcredit=0;
    integer cpu_mask[0:255];
    integer trace_fd,ram_fd,fd,rc,words=0,index,frame_index;
    string input_path,expected_path,rom_path,wave,trace_path,ram_path;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d frame=%0d read=%0d write=%0d",cycles,completed,rd_pixels,wr_pixels);end
    endtask
    task clear_epoch;
        begin
            pixels=0;completed=0;irqs=0;cpu_checks=0;rd_pixels=0;wr_pixels=0;issued=0;addressed=0;rleft=0;wleft=0;bcredit=0;apb_errors=0;ahb_errors=0;b_count=0;cpu_stores=0;
            ar_hold=0;aw_hold=0;w_hold=0;r_hold=0;apb_hold=0;ahb_hold=0;b_hold=0;irq_old=0;invalid_seen=0;error_first=0;cpu_hold=0;irq_gate=0;
            for(integer j=0;j<256;j=j+1)cpu_mask[j]=0;
        end
    endtask
    initial begin
        if(!$value$plusargs("INPUT=%s",input_path) || !$value$plusargs("EXPECTED=%s",expected_path) ||
           !$value$plusargs("ROM=%s",rom_path) || !$value$plusargs("WAVE=%s",wave) ||
           !$value$plusargs("TRACE=%s",trace_path) || !$value$plusargs("RAMFILE=%s",ram_path) ||
           !$value$plusargs("FRAMES=%d",frames) || !$value$plusargs("SEED=%d",seed) ||
           !$value$plusargs("SCENARIO=%d",scenario) || !$value$plusargs("FAULT=%d",fault) || !$value$plusargs("SRC_BASE=%d",src_base) ||
           !$value$plusargs("DST_BASE=%d",dst_base) || !$value$plusargs("APB_ERRORS=%d",expected_apb) || !$value$plusargs("AHB_ERRORS=%d",expected_ahb))$fatal(1,"arguments required");
        if(frames*N>256)$fatal(1,"capacity exceeded");
        #1; // The ROM module's default initialization precedes the harness image load.
        $readmemh(input_path,inputs,0,frames*N-1);$readmemh(expected_path,golden,0,frames*N-1);
        for(integer j=0;j<1024;j=j+1)begin dut.memory.rom[j]=32'h00000013;rom_words[j]=32'h00000013;end
        fd=$fopen(rom_path,"r");if(!fd)$fatal(1,"ROM missing");
        while(!$feof(fd))begin
            rc=$fscanf(fd,"%h\n",rom_words[words]);if(rc!=1 || words>=1024)$fatal(1,"ROM invalid");
            dut.memory.rom[words]=rom_words[words];words=words+1;
        end
        $fclose(fd);trace_fd=$fopen(trace_path,"w");ram_fd=$fopen(ram_path,"w");
        if(!trace_fd || !ram_fd)$fatal(1,"trace output failed");
        $dumpfile(wave);$dumpvars(2,image_soc_tb);
        rng=32'(seed)|1;
        clear_epoch();repeat(4)@(negedge clk);rst_n=1;
        while(!halted)begin
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            memory_allow={rng[8:7]!=0,rng[6:5]!=0,rng[4:3]!=0,rng[2:1]!=0,rng[0]||rng[9]};
            // Scenario 9 does not leave the overlap to the seed: the last pixel waits until the CPU is held on a
            // RAM access, and the CPU stays held there until the interrupt has been up for one cycle.
            if(scenario==9)begin
                if(irq_gate==0 && wr_pixels==N-1)begin
                    memory_allow[4:3]=0;
                    if(cpu_hold && cpu_held[31:12]==20'h1)irq_gate=1;
                end else if(irq_gate==1)begin
                    memory_allow[4]=0;
                    if(irq && irq_old)irq_gate=2;
                end else if(irq_gate==2 && wr_pixels<N-1)irq_gate=0;
            end
            // FAULT<0 hits every response; otherwise only that read beat or write burst answers SLVERR.
            read_error=scenario==1 && (fault<0 || rd_pixels==fault);write_error=scenario==2 && (fault<0 || b_count==fault);
            #1;
            if((^{halted,bus_fault,irq,busy,done,error,dut.hready,dut.hresp,dut.arvalid,dut.awvalid,dut.wvalid,dut.rvalid,dut.bvalid})===1'bx)fail("SOC_UNKNOWN");
            if((^{dut.htrans,dut.cpu_valid,dut.cpu_ready})===1'bx)fail("SOC_UNKNOWN");
            if(dut.htrans[1] && (^{dut.haddr,dut.hwrite,dut.hsize,dut.hburst})===1'bx)fail("SOC_UNKNOWN");
            if(dut.arvalid && (^{dut.araddr,dut.arlen,dut.arsize,dut.arburst,dut.arid})===1'bx)fail("SOC_UNKNOWN");
            if(dut.awvalid && (^{dut.awaddr,dut.awlen,dut.awsize,dut.awburst,dut.awid})===1'bx)fail("SOC_UNKNOWN");
            if(dut.wvalid && (^{dut.wdata,dut.wstrb,dut.wlast})===1'bx)fail("SOC_UNKNOWN");
            if(dut.rvalid && (^{dut.rdata,dut.rid,dut.rresp,dut.rlast})===1'bx)fail("SOC_UNKNOWN");
            if(dut.bvalid && (^{dut.bid,dut.bresp})===1'bx)fail("SOC_UNKNOWN");
            if(ahb_hold && {dut.haddr,dut.hwdata,dut.hwrite,dut.htrans,dut.hsize,dut.hburst}!==held_ahb)fail("SOC_AHB_HOLD");
            ahb_hold=!dut.hready;held_ahb={dut.haddr,dut.hwdata,dut.hwrite,dut.htrans,dut.hsize,dut.hburst};
            if(dut.htrans[1] && dut.hready)begin
                if(dut.haddr!==dut.cpu_addr || dut.hwrite!==dut.cpu_write || dut.hsize!=2 || dut.hburst!=0)fail("SOC_AHB");
                $display("COVER bus/ahb-address");
            end
            if(dut.cpu_valid && !dut.cpu_ready)$display("COVER bus/ahb-wait");
            if(dut.hresp && dut.hready && !error_first)fail("SOC_AHB_RESPONSE");
            error_first=dut.hresp && !dut.hready;
            if(dut.psel)begin
                if((^{dut.penable,dut.pwrite,dut.paddr,dut.pready,dut.pslverr})===1'bx)fail("SOC_UNKNOWN");
                if(dut.paddr!==dut.cpu_addr[7:0] || dut.pwrite!==dut.cpu_write || (dut.pwrite && dut.pwdata!==dut.cpu_wdata))fail("SOC_APB");
                if(!dut.penable)$display("COVER bus/apb-setup");
            end
            if(apb_hold && (!dut.psel || !dut.penable || {dut.paddr,dut.pwrite,dut.pwdata}!==held_apb[40:0]))fail("SOC_APB_HOLD");
            apb_hold=dut.psel && dut.penable && !dut.pready;held_apb={16'd0,dut.paddr,dut.pwrite,dut.pwdata};
            if(apb_hold)$display("COVER bus/apb-wait");
            if(dut.psel && dut.penable && dut.pready && dut.pslverr)begin apb_errors=apb_errors+1;$display("COVER bus/apb-error");end
            if(dut.hresp && dut.hready)begin
                ahb_errors=ahb_errors+1;$display("COVER bus/ahb-error");
                if(dut.cpu_addr>=32'h2000 && dut.cpu_addr[31:8]!=24'h400000)$display("COVER bus/unmapped-error");
            end
            if(dut.psel && dut.penable && dut.pready && !dut.pwrite && dut.paddr==20)begin
                if(dut.prdata!==((32'(H)<<16)|32'(W)))fail("SOC_REG");
                $display("COVER reg/shape-read");
            end
            if(ar_hold && (!dut.arvalid || {dut.araddr,dut.arlen,dut.arsize,dut.arburst,dut.arid}!==held_ar))fail("SOC_AXI_HOLD");
            if(aw_hold && (!dut.awvalid || {dut.awaddr,dut.awlen,dut.awsize,dut.awburst,dut.awid}!==held_aw))fail("SOC_AXI_HOLD");
            if(w_hold && (!dut.wvalid || {dut.wdata,dut.wstrb,dut.wlast}!==held_w))fail("SOC_AXI_HOLD");
            if(r_hold && (!dut.rvalid || {dut.rdata,dut.rid,dut.rresp,dut.rlast}!==held_r))fail("SOC_AXI_HOLD");
            if(b_hold && (!dut.bvalid || {dut.bid,dut.bresp}!==held_b))fail("SOC_AXI_HOLD");
            ar_hold=dut.arvalid && !dut.arready;held_ar={dut.araddr,dut.arlen,dut.arsize,dut.arburst,dut.arid};
            aw_hold=dut.awvalid && !dut.awready;held_aw={dut.awaddr,dut.awlen,dut.awsize,dut.awburst,dut.awid};
            w_hold=dut.wvalid && !dut.wready;held_w={dut.wdata,dut.wstrb,dut.wlast};
            r_hold=dut.rvalid && !dut.rready;held_r={dut.rdata,dut.rid,dut.rresp,dut.rlast};
            b_hold=dut.bvalid && !dut.bready;held_b={dut.bid,dut.bresp};
            if(ar_hold || aw_hold || w_hold || r_hold)$display("COVER bus/axi-backpressure");
            if(dut.arvalid && dut.arready)begin
                if(rleft!=0 || dut.araddr!=32'(src_base)+32'(4*issued) || dut.arsize!=2 || dut.arburst!=1 || dut.arid!=0 ||
                   dut.arlen!=(N-issued>=4 ? 3 : N-issued-1))fail("SOC_AXI_READ");
                rleft=int'(dut.arlen)+1;issued=issued+rleft;$display("COVER dma/read-burst");
                if(dut.arlen!=3)$display("COVER dma/tail-burst");
            end
            if(dut.rvalid && dut.rready)begin
                if(rleft==0 || dut.rid!=0 || dut.rlast!=(rleft==1) || dut.rresp!=(scenario==1 && (fault<0 || rd_pixels==fault) ? 2 : 0) ||
                   dut.rdata!=={24'd0,inputs[completed*N+rd_pixels]})fail("SOC_AXI_READ");
                rleft=rleft-1;rd_pixels=rd_pixels+1;
                if(dut.rresp!=0)$display("COVER dma/read-error");
                if(dut.rresp!=0 && fault>=0)$display("COVER dma/read-error-single");
            end
            if(dut.awvalid && dut.awready)begin
                if(bcredit!=0 || wleft!=0 || dut.awaddr!=32'(dst_base)+32'(4*addressed) || dut.awsize!=2 || dut.awburst!=1 || dut.awid!=0 ||
                   dut.awlen!=(N-addressed>=4 ? 3 : N-addressed-1))fail("SOC_AXI_WRITE");
                wleft=int'(dut.awlen)+1;addressed=addressed+wleft;bcredit=1;$display("COVER dma/write-burst");
                if(src_base!=4096)$display("COVER config/relocated");
            end
            if(dut.wvalid && dut.wready)begin
                if(wleft==0 || dut.wlast!=(wleft==1) || dut.wstrb!=1)fail("SOC_AXI_WRITE");
                if(dut.wdata!=={24'd0,golden[completed*N+wr_pixels]})fail("SOC_PIXEL");
                wleft=wleft-1;wr_pixels=wr_pixels+1;pixels=pixels+1;
            end
            if(dut.bvalid && dut.bready)begin
                if(bcredit!=1 || wleft!=0 || dut.bid!=0 || dut.bresp!=(scenario==2 && (fault<0 || b_count==fault) ? 2 : 0))fail("SOC_AXI_WRITE");
                bcredit=0;b_count=b_count+1;
                if(dut.bresp!=0)$display("COVER dma/write-error");
                if(dut.bresp!=0 && fault>=0)$display("COVER dma/write-error-single");
                if(wr_pixels==N)$display("COVER completion/last-b-response");
            end
            if(dut.ram_req && !dut.ram_ready && dut.wvalid && dut.wready)$display("COVER ram/cpu-dma-contention");
            if(dut.ram_req && dut.ram_write && !dut.ram_ready && dut.wvalid && dut.wready)$display("COVER ram/cpu-store-contention");
            if(irq && !irq_old)begin
                irqs=irqs+1;
                if(scenario==3 && invalid_seen<9)begin
                    if(busy || done || !error || issued!=0 || addressed!=0 || bcredit!=0)fail("SOC_INVALID_CONFIG");
                    if(invalid_seen==0)$display("COVER config/unaligned");
                    else if(invalid_seen==1)$display("COVER config/range");
                    else if(invalid_seen==2)$display("COVER config/overlap");
                    else if(invalid_seen<=4)$display("COVER config/destination");
                    else if(invalid_seen<=6)$display("COVER config/below-ram");
                    else $display("COVER config/overlap-either");
                    invalid_seen=invalid_seen+1;$display("COVER config/rejected");
                end else begin
                    if(busy || rleft!=0 || bcredit!=0 || wleft!=0 || rd_pixels!=N || wr_pixels!=N)fail("SOC_COMPLETION");
                    if(done!==(scenario!=1 && scenario!=2) || error!==(scenario==1 || scenario==2))fail("SOC_STATUS");
                    for(integer j=0;j<N;j=j+1)begin
                        if(dut.memory.ram[(dst_base-4096)/4+j]!== (32'ha5a50000|32'(golden[completed*N+j])))fail("SOC_RAM");
                        $fdisplay(ram_fd,"%08x",dut.memory.ram[(dst_base-4096)/4+j]);
                    end
                    completed=completed+1;rd_pixels=0;wr_pixels=0;issued=0;addressed=0;b_count=0;
                    $display("COVER completion/irq");
                    if(completed>1)$display("COVER frame/restart");
                end
            end
            irq_old=irq;
            // The adapter cannot take an access back from the bus, so the CPU must hold one until it is answered.
            // An interrupt is the one event that could make the CPU drop it.
            if(cpu_hold && (!dut.cpu_valid || {dut.cpu_write,dut.cpu_addr}!==cpu_held))fail("SOC_CPU_HOLD");
            if(cpu_hold && dut.cpu_valid && irq && dut.cpu.st_mie && dut.cpu.ie_meie)$display("COVER irq/waits-for-access");
            cpu_hold=dut.cpu_valid && !dut.cpu_ready;cpu_held={dut.cpu_write,dut.cpu_addr};
            if(dut.cpu_valid && dut.cpu_ready)begin
                if(dut.cpu_write && dut.cpu_be!=15)fail("SOC_CPU_ACCESS");
                if(!dut.cpu_write && dut.cpu_addr<32'h1000)$display("COVER boot/rom-data");
                if(!dut.cpu_write && dut.cpu_addr>=32'(dst_base) && dut.cpu_addr<32'(dst_base)+4*N)begin
                    if(completed==0)fail("SOC_FIRMWARE");
                    index=int'((dut.cpu_addr-32'(dst_base))/4);frame_index=completed-1;
                    if(dut.cpu_rdata!==(32'ha5a50000|32'(golden[frame_index*N+index])) || cpu_mask[frame_index*N+index]!=0)fail("SOC_FIRMWARE");
                    cpu_mask[frame_index*N+index]=1;cpu_checks=cpu_checks+1;$display("COVER firmware/pixel-check");
                end
            end
            if(ret_valid)begin
                if(ret_pc>=4*words || ret_pc[1:0]!=0 || ret_insn!==rom_words[ret_pc/4])fail("SOC_ROM");
                $fdisplay(trace_fd,"%08x %08x %0d %0d %08x %08x %08x",ret_pc,ret_insn,ret_rd,ret_mem,ret_wdata,ret_mem_addr,ret_mem_data);
                if(ret_pc==0)$display("COVER boot/rom");
                if(ret_mem==3)begin
                    if(ret_mem_addr!=32'h8000000b)fail("SOC_TRAP");
                    $display("COVER firmware/interrupt");
                end
                if(ret_insn==32'h30200073)$display("COVER firmware/mret");
                if(ret_mem==2 && ret_mem_addr==32'h1800)cpu_stores=cpu_stores+1;
            end
            @(posedge clk);#1;@(negedge clk);
            if(!reset_done && ((scenario==5 && rd_pixels>=3) || (scenario==6 && wr_pixels>=2)))begin
                rst_n=0;memory_allow=0;
                repeat(4)@(negedge clk);
                clear_epoch();$fclose(ram_fd);ram_fd=$fopen(ram_path,"w");
                reset_done=1;rst_n=1;
                if(scenario==5)$display("COVER reset/read-inflight");else $display("COVER reset/write-inflight");
                $fdisplay(trace_fd,"RESET");
            end
            cycles=cycles+1;if(cycles>200000)fail("SOC_TIMEOUT");
        end
        if(completed!=frames || pixels!=frames*N || irqs!=frames+9*(scenario==3) ||
           cpu_checks!=(scenario==1 || scenario==2 ? 0 : frames*N) ||
           (scenario==3 && invalid_seen!=9) || ((scenario==5 || scenario==6) && !reset_done) ||
           bus_fault!==(scenario==4) || dut.memory.ram[1023]!==32'h600d600d)fail("SOC_FIRMWARE");
        // Every retired store to the scratch counter must be in RAM, including those stalled behind a DMA write.
        if(dut.memory.ram[512]!==32'(cpu_stores))fail("SOC_CPU_RAM");
        if(apb_errors!=expected_apb || ahb_errors!=expected_ahb)fail("SOC_BUS_ERRORS");
        $display("COUNT frames=%0d",completed);$display("COUNT pixels=%0d",pixels);
        $display("COUNT irqs=%0d",irqs);$display("COUNT cpu_checks=%0d",cpu_checks);$display("COUNT resets=%0d",reset_done);
        $display("RESULT PASS checks=%0d",pixels);$fclose(trace_fd);$fclose(ram_fd);$finish;
    end
endmodule
