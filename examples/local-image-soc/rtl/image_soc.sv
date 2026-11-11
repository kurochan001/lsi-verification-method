// Single-clock uncached RV32I teaching SoC. All data traffic uses the AHB adapter.
module image_soc #(parameter W=5,H=5,WAIT_CYCLES=0,MUTATION=0,parameter ROM_FILE="")(
    input wire clk,rst_n,input wire [4:0] memory_allow,input wire read_error,write_error,
    output wire halted,bus_fault,irq,busy,done,error,
    output wire ret_valid,output wire [31:0] ret_pc,ret_insn,ret_wdata,ret_mem_addr,ret_mem_data,
    output wire [4:0] ret_rd,output wire [1:0] ret_mem,
    output wire [31:0] perf_ctrl,perf_flush
);
    wire [31:0] imem_addr,imem_data,cpu_addr,cpu_wdata,cpu_rdata;
    wire cpu_valid,cpu_write,cpu_ready;
    wire [3:0] cpu_be;
    // Hold the synchronous-reset core through two clock edges after external release.
    reg [1:0] cpu_release;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)cpu_release<=0;else cpu_release<={cpu_release[0],1'b1};
    end
    rv32i_core #(.TRAPS(1),.MUTATION(MUTATION==5 ? 17:0)) cpu(
        .clk(clk),.rst_n(cpu_release[1]),.irq(irq),.imem_addr(imem_addr),.imem_data(imem_data),
        .dmem_valid(cpu_valid),.dmem_we(cpu_write),.dmem_addr(cpu_addr),.dmem_wdata(cpu_wdata),.dmem_be(cpu_be),
        .dmem_rdata(cpu_rdata),.dmem_ready(cpu_ready),.ret_valid(ret_valid),.ret_pc(ret_pc),.ret_insn(ret_insn),
        .ret_wdata(ret_wdata),.ret_mem_addr(ret_mem_addr),.ret_mem_data(ret_mem_data),.ret_rd(ret_rd),.ret_mem(ret_mem),
        .perf_ctrl(perf_ctrl),.perf_flush(perf_flush),.halted(halted));
    // The SoC contract uses aligned LW/SW only; the bench checks cpu_be on stores.
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_be=&{1'b0,cpu_be};
    /* verilator lint_on UNUSEDSIGNAL */
    wire [31:0] haddr,hwdata,hrdata;
    wire [1:0] htrans;
    wire [2:0] hsize,hburst;
    wire hwrite,hready,hresp;
    cpu_ahb #(.MUTATION(MUTATION)) adapter(.*);
    wire ram_req,ram_write,ram_ready;
    wire [31:0] ram_addr,ram_wdata,ram_rdata,rom_addr,rom_rdata;
    wire psel,penable,pwrite,pready,pslverr;
    wire [7:0] paddr;
    wire [31:0] pwdata,prdata;
    image_fabric #(.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) fabric(.*);
    wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [31:0] araddr,awaddr,rdata,wdata;
    wire [7:0] arlen,awlen;
    wire [2:0] arsize,awsize;
    wire [1:0] arburst,arid,rid,rresp,awburst,awid,bid,bresp;
    wire [3:0] wstrb;
    image_dma #(.W(W),.H(H),.WAIT_CYCLES(WAIT_CYCLES+1),.MUTATION(MUTATION)) image(.*);
    image_memory #(.ROM_FILE(ROM_FILE)) memory(.clk(clk),.rst_n(rst_n),.allow(memory_allow),.read_error(read_error),.write_error(write_error),
        .imem_addr(imem_addr),.imem_data(imem_data),.rom_addr(rom_addr),.rom_data(rom_rdata),
        .cpu_req(ram_req),.cpu_write(ram_write),.cpu_addr(ram_addr),.cpu_wdata(ram_wdata),.cpu_ready(ram_ready),.cpu_rdata(ram_rdata),
        .arvalid(arvalid),.araddr(araddr),.arlen(arlen),.arsize(arsize),.arburst(arburst),.arid(arid),.arready(arready),
        .rvalid(rvalid),.rdata(rdata),.rid(rid),.rresp(rresp),.rlast(rlast),.rready(rready),
        .awvalid(awvalid),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),.awid(awid),.awready(awready),
        .wvalid(wvalid),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wready(wready),
        .bvalid(bvalid),.bid(bid),.bresp(bresp),.bready(bready));
endmodule
