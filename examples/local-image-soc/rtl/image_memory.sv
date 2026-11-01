// 4 KiB ROM + 4 KiB shared RAM. CPU accesses wait behind an accepted AXI write.
// AXI4 subset: aligned 32-bit INCR, 1..4 beats, one outstanding per direction.
// RAM is cleared by whole-SoC reset; ROM is loaded by the simulation harness.
module image_memory #(parameter B_DELAY=5,parameter ROM_FILE="")(
    input wire clk,rst_n,input wire [4:0] allow,
    input wire read_error,write_error,
    input wire [31:0] imem_addr,rom_addr,output wire [31:0] imem_data,rom_data,
    input wire cpu_req,cpu_write,input wire [31:0] cpu_addr,cpu_wdata,
    output wire cpu_ready,output wire [31:0] cpu_rdata,
    input wire arvalid,input wire [31:0] araddr,input wire [7:0] arlen,
    input wire [2:0] arsize,input wire [1:0] arburst,arid,output wire arready,
    output reg rvalid,output reg [31:0] rdata,output reg [1:0] rid,rresp,
    output reg rlast,input wire rready,
    input wire awvalid,input wire [31:0] awaddr,input wire [7:0] awlen,
    input wire [2:0] awsize,input wire [1:0] awburst,awid,output wire awready,
    input wire wvalid,input wire [31:0] wdata,input wire [3:0] wstrb,input wire wlast,output wire wready,
    output reg bvalid,output reg [1:0] bid,bresp,input wire bready
);
    reg [31:0] rom[0:1023],ram[0:1023];
    initial begin
        for(integer j=0;j<1024;j=j+1)rom[j]=32'h00000013;
        if(ROM_FILE!="")$readmemh(ROM_FILE,rom);
    end
    reg reading,writing,read_bad,write_bad,bpending;
    reg [9:0] read_base,write_base;
    reg [7:0] read_length,write_length,read_beat,write_beat;
    reg [1:0] read_id,write_id;
    integer bdelay;
    function automatic invalid(input [31:0] address,input [7:0] length,input [2:0] size,input [1:0] burst);
        reg [32:0] finish;
        begin
            finish={1'b0,address}+(33'(length)+1)*4;
            invalid=address<32'h1000 || finish>33'h2000 || address[1:0]!=0 || size!=2 || burst!=1 || length>3 ||
                    (int'(address[11:0])+(int'(length)+1)*4)>4096;
        end
    endfunction
    assign imem_data=imem_addr<4096 && imem_addr[1:0]==0 ? rom[imem_addr[11:2]] : 32'h00000013;
    assign rom_data=rom_addr<4096 && rom_addr[1:0]==0 ? rom[rom_addr[11:2]] : 32'd0;
    assign arready=rst_n && !reading && !rvalid && allow[0];
    assign awready=rst_n && !writing && !bpending && !bvalid && allow[2];
    assign wready=rst_n && writing && allow[3];
    assign cpu_ready=rst_n && allow[4] && !(wvalid && wready);
    wire cpu_address_ok=cpu_addr>=32'h1000 && cpu_addr<32'h2000 && cpu_addr[1:0]==0;
    assign cpu_rdata=cpu_address_ok ? ram[cpu_addr[11:2]] : 32'd0;
    wire [9:0] read_index=read_base+10'(read_beat);
    wire [9:0] write_index=write_base+10'(write_beat);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            reading<=0;writing<=0;read_bad<=0;write_bad<=0;bpending<=0;
            read_base<=0;write_base<=0;read_length<=0;write_length<=0;read_beat<=0;write_beat<=0;read_id<=0;write_id<=0;
            rvalid<=0;rdata<=0;rid<=0;rresp<=0;rlast<=0;bvalid<=0;bid<=0;bresp<=0;bdelay<=0;
            for(integer j=0;j<1024;j=j+1)ram[j]<=0;
        end else begin
            if(cpu_req && cpu_ready && cpu_write && cpu_address_ok)ram[cpu_addr[11:2]]<=cpu_wdata;
            if(arvalid && arready)begin
                reading<=1;read_base<=araddr[11:2];read_length<=arlen;read_beat<=0;read_id<=arid;
                read_bad<=invalid(araddr,arlen,arsize,arburst);
            end
            if(reading && !rvalid && allow[1])begin
                rvalid<=1;rdata<=read_bad ? 0 : ram[read_index];
                rid<=read_id;rresp<=read_bad || read_error ? 2'b10 : 2'b00;rlast<=read_beat==read_length;
            end
            if(rvalid && rready)begin
                rvalid<=0;
                if(rlast)reading<=0;else read_beat<=read_beat+1'b1;
            end
            if(awvalid && awready)begin
                writing<=1;write_base<=awaddr[11:2];write_length<=awlen;write_beat<=0;write_id<=awid;
                write_bad<=invalid(awaddr,awlen,awsize,awburst);
            end
            if(wvalid && wready)begin
                if(!write_bad)for(integer k=0;k<4;k=k+1)if(wstrb[k])ram[write_index][8*k+:8]<=wdata[8*k+:8];
                if(wlast!=(write_beat==write_length))write_bad<=1;
                if(write_beat==write_length)begin
                    writing<=0;bpending<=1;bdelay<=B_DELAY;bid<=write_id;
                    bresp<=write_bad || write_error || !wlast ? 2'b10 : 2'b00;
                end else write_beat<=write_beat+1'b1;
            end
            if(bpending)begin
                if(bdelay!=0)bdelay<=bdelay-1;
                else begin bvalid<=1;bpending<=0;end
            end
            if(bvalid && bready)bvalid<=0;
        end
    end
endmodule
