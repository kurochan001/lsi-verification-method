// Educational AXI4 subset: 32-bit aligned INCR, up to four beats, two credits per direction.
module axi4_ram #(parameter MUTATION=0,MEM_BYTES=8192,CHECK_INVARIANTS=1,ABSTRACT_DATA=0)(
 input wire clk,rst_n,
 input wire awvalid,input wire [12:0] awaddr,input wire [7:0] awlen,
 input wire [2:0] awsize,input wire [1:0] awburst,awid,output wire awready,
 input wire wvalid,input wire [31:0] wdata,input wire [3:0] wstrb,input wire wlast,output wire wready,
 output wire bvalid,input wire bready,output wire [1:0] bid,bresp,
 input wire arvalid,input wire [12:0] araddr,input wire [7:0] arlen,
 input wire [2:0] arsize,input wire [1:0] arburst,arid,output wire arready,
 output reg rvalid,input wire rready,output reg [31:0] rdata,output reg [1:0] rid,rresp,output wire rlast
`ifdef FORMAL
 ,output wire [1:0] formal_wc,formal_rc,formal_wqueued
`endif
);
 reg [7:0] memory[0:MEM_BYTES-1];
 reg [12:0] wa[0:1],ra[0:1];
 reg [7:0] wl[0:1],rl[0:1];
 reg [1:0] wi[0:1],ri[0:1];
 reg we[0:1],re[0:1],done[0:1];
 reg awtail,whead,bhead,artail,rhead;
 reg [1:0] wc,rc,wqueued; // Accepted addresses minus completed responses, including data processing.
 reg [7:0] wbeat,rbeat;
 reg read_last;
 integer j,k,base;
 function automatic invalid(input [12:0] address,input [7:0] length,input [2:0] size,input [1:0] burst);
   integer finish;
   begin
     finish={1'b0,address}+(length+1)*4;
     invalid=address[1:0]!=0 || size!=2 || burst!=1 || length>3 || finish>MEM_BYTES ||
             ({1'b0,address[11:0]}+(length+1)*4)>4096;
   end
 endfunction
 assign awready=rst_n && wc<2;
 assign wready=rst_n && wqueued!=0;
 assign bvalid=rst_n && wc!=0 && done[bhead];
 assign bid=wi[bhead] ^ (MUTATION==2 ? 2'b01:2'b00);
 assign bresp=we[bhead] ? 2'b10:2'b00;
 assign arready=rst_n && rc<2;
 assign rlast=read_last ^ (MUTATION==3);
`ifdef FORMAL
 assign formal_wc=wc;assign formal_rc=rc;assign formal_wqueued=wqueued;
 (* anyseq *)wire [31:0] formal_read_data;
 reg formal_past=0;
 always @(posedge clk)formal_past<=1;
 generate if(CHECK_INVARIANTS)begin
  always @(posedge clk)if(formal_past && rst_n)begin
   ai_fifo_bounds:assert(wc<=2 && rc<=2 && wqueued<=2);
   ai_write_accounting:assert(wc==int'(wqueued)+int'(done[0])+int'(done[1]));
   ai_write_pointers:assert(awtail==((int'(whead)+int'(wqueued))%2) && awtail==((int'(bhead)+int'(wc))%2));
   ai_write_head:assert((wqueued==0 || !done[whead]) && (!(done[0] || done[1]) || done[bhead]));
   ai_read_pending:assert(!rvalid || rc!=0);
   ai_read_pointers:assert(artail==((int'(rhead)+int'(rc))%2));
  end
 end endgenerate
`endif
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
     awtail<=0;whead<=0;bhead<=0;artail<=0;rhead<=0;wc<=0;rc<=0;wqueued<=0;wbeat<=0;rbeat<=0;
     rvalid<=0;rdata<=0;rid<=0;rresp<=0;read_last<=0;
     for(j=0;j<2;j=j+1) begin wa[j]<=0;ra[j]<=0;wl[j]<=0;rl[j]<=0;wi[j]<=0;ri[j]<=0;we[j]<=0;re[j]<=0;done[j]<=0;end
     for(j=0;j<MEM_BYTES;j=j+1) memory[j]<=0;
   end else begin
     case({awvalid&&awready,bvalid&&bready})
       2'b10:wc<=wc+1'b1;2'b01:wc<=wc-1'b1;default:;
     endcase
     case({awvalid&&awready,wvalid&&wready&&(wbeat==wl[whead])})
       2'b10:wqueued<=wqueued+1'b1;2'b01:wqueued<=wqueued-1'b1;default:;
     endcase
     if(awvalid&&awready) begin
       wa[awtail]<=awaddr;wl[awtail]<=awlen;wi[awtail]<=awid;
       we[awtail]<=invalid(awaddr,awlen,awsize,awburst);done[awtail]<=0;awtail<=!awtail;
     end
     if(wvalid&&wready) begin
       base=wa[whead]+4*wbeat;
       // Unsupported requests have no write side effects. WLAST errors return SLVERR.
       // A late WLAST error does not roll back earlier legal beats.
       if(!we[whead]) for(k=0;k<4;k=k+1)
         if(wstrb[k] || MUTATION==4) memory[base+k]<=wdata[8*k+:8];
       if(wlast!=(wbeat==wl[whead])) we[whead]<=1;
       if(wbeat==wl[whead]) begin done[whead]<=1;whead<=!whead;wbeat<=0;end
       else wbeat<=wbeat+1'b1;
     end
     if(bvalid&&bready) begin done[bhead]<=0;bhead<=!bhead;end
     case({arvalid&&arready,rvalid&&rready&&read_last})
       2'b10:rc<=rc+1'b1;2'b01:rc<=rc-1'b1;default:;
     endcase
     if(arvalid&&arready) begin
       ra[artail]<=araddr;rl[artail]<=arlen;ri[artail]<=arid;
       re[artail]<=invalid(araddr,arlen,arsize,arburst);artail<=!artail;
     end
     // Register every beat, so R payload stays stable if a concurrent write changes memory.
     if(!rvalid && rc!=0) begin
       base=ra[rhead]+4*rbeat;
`ifdef FORMAL
       if(ABSTRACT_DATA)rdata<=formal_read_data;
       else begin
`endif
       rdata<=re[rhead] ? 0 : {memory[base+3],memory[base+2],memory[base+1],memory[base]};
       if(MUTATION==1 && !re[rhead]) rdata<={memory[base+3],memory[base+2],memory[base+1],memory[base]} ^ 32'b1;
`ifdef FORMAL
       end
`endif
       rid<=ri[rhead];rresp<=re[rhead] ? 2:0;read_last<=rbeat==rl[rhead];rvalid<=1;
     end else if(rvalid&&rready) begin
       rvalid<=0;
       if(read_last) begin rhead<=!rhead;rbeat<=0;end else rbeat<=rbeat+1'b1;
     end
   end
 end
endmodule
