// APB-controlled, non-overlapping, word-aligned memcpy DMA; one AXI burst at a time.
module apb_dma #(parameter MUTATION=0)(
 input wire clk,rst_n,psel,penable,pwrite,input wire [7:0] paddr,input wire [31:0] pwdata,
 output wire pready,pslverr,output reg [31:0] prdata,output wire irq,
 output wire arvalid,input wire arready,output wire [12:0] araddr,output wire [7:0] arlen,output wire [1:0] arid,
 input wire rvalid,output wire rready,input wire [31:0] rdata,input wire [1:0] rid,rresp,input wire rlast,
 output wire awvalid,input wire awready,output wire [12:0] awaddr,output wire [7:0] awlen,output wire [1:0] awid,
 output wire wvalid,input wire wready,output wire [31:0] wdata,output wire [3:0] wstrb,output wire wlast,
 input wire bvalid,output wire bready,input wire [1:0] bid,bresp
);
 localparam IDLE=0,AR=1,READ=2,AW=3,WRITE=4,B=5;
 reg [2:0] state;reg [31:0] source_reg,dest_reg,words_reg;
 reg [12:0] source,destination;reg [31:0] remaining;reg [2:0] chunk,beat;
 reg done,error,aborted,irq_pending,irq_enable,abort_pending,read_error;
 reg [31:0] buffer[0:3];
 wire busy=state!=IDLE;
 wire access=psel && penable;
 assign pready=access;
 wire known=paddr==0 || paddr==4 || paddr==8 || paddr==12 || paddr==16 || paddr==20;
 assign pslverr=access && (!known || paddr[1:0]!=0 || (pwrite && (paddr==16 || (busy && paddr<=8) ||
    (paddr==12 && ((pwdata[0] && busy) || pwdata[1:0]==3)))));
 wire command=access && pwrite && !pslverr && paddr==12;
 wire abort_now=command && pwdata[1];
 assign irq=irq_pending && irq_enable;
 always @*case(paddr)
  0:prdata=source_reg;4:prdata=dest_reg;8:prdata=words_reg;12:prdata=0;
  16:prdata={27'b0,irq_pending,aborted,error,done,busy};20:prdata={31'b0,irq_enable};default:prdata=0;
 endcase
 function automatic [2:0] burst_length(input [31:0] left,input [12:0] src,dst);
  integer count,src_limit,dst_limit;begin
   count=left<4 ? left:4;src_limit=(4096-src[11:0])/4;dst_limit=(4096-dst[11:0])/4;
   if(MUTATION!=1)begin if(count>src_limit)count=src_limit;if(count>dst_limit)count=dst_limit;end
   burst_length=count;
  end
 endfunction
 assign arvalid=rst_n && state==AR;assign araddr=source;assign arlen=chunk-1'b1;assign arid=1;
 assign rready=rst_n && state==READ;
 assign awvalid=rst_n && state==AW;assign awaddr=destination;assign awlen=chunk-1'b1;assign awid=2;
 assign wvalid=rst_n && state==WRITE;assign wdata=buffer[beat] ^ (MUTATION==2 ? 32'b1:0);assign wstrb=15;assign wlast=beat==chunk-1;
 assign bready=rst_n && state==B;
 task finish(input bad,input stopped);begin state<=IDLE;done<=1;error<=bad;aborted<=stopped;irq_pending<=MUTATION!=3;end endtask
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=IDLE;source_reg<=0;dest_reg<=0;words_reg<=0;source<=0;destination<=0;remaining<=0;chunk<=0;beat<=0;
   done<=0;error<=0;aborted<=0;irq_pending<=0;irq_enable<=1;abort_pending<=0;read_error<=0;
   for(integer i=0;i<4;i=i+1)buffer[i]<=0;
  end else begin
   if(access && pwrite && !pslverr)case(paddr)
    0:source_reg<=pwdata;4:dest_reg<=pwdata;8:words_reg<=pwdata;20:irq_enable<=pwdata[0];default:;
   endcase
   if(command && pwdata[2])irq_pending<=0;
   if(abort_now && busy)abort_pending<=1;
   case(state)
    IDLE:if(command && pwdata[0])begin
     done<=0;error<=0;aborted<=0;irq_pending<=0;abort_pending<=0;read_error<=0;beat<=0;
     source<=source_reg[12:0];destination<=dest_reg[12:0];remaining<=words_reg;
     chunk<=burst_length(words_reg,source_reg[12:0],dest_reg[12:0]);
     if(words_reg>32 || source_reg[1:0]!=0 || dest_reg[1:0]!=0 || source_reg>8192 || dest_reg>8192 ||
        source_reg+words_reg*4>8192 || dest_reg+words_reg*4>8192 ||
        (words_reg!=0 && source_reg<dest_reg+words_reg*4 && dest_reg<source_reg+words_reg*4))finish(1,0);
     else if(words_reg==0)finish(0,0);else state<=AR;
    end
    AR:if(arready)begin state<=READ;beat<=0;read_error<=0;end
    READ:if(rvalid)begin
     buffer[beat]<=rdata;read_error<=read_error || rresp!=0 || rid!=1 || rlast!=(beat==chunk-1);
     if(beat==chunk-1)begin
      beat<=0;
      if(read_error || rresp!=0 || rid!=1 || !rlast)finish(1,0);
      else if(abort_pending || abort_now)finish(0,1);
      else state<=AW;
     end else beat<=beat+1'b1;
    end
    AW:if(awready)begin state<=WRITE;beat<=0;end
    WRITE:if(wready)begin if(wlast)begin state<=B;beat<=0;end else beat<=beat+1'b1;end
    B:if(bvalid)begin
     if(bresp!=0 || bid!=2)finish(1,0);
     else if(abort_pending || abort_now)finish(0,1);
     else if(remaining==chunk)finish(0,0);
     else begin
      source<=source+4*chunk;destination<=destination+(MUTATION==4 ? chunk:4*chunk);remaining<=remaining-chunk;
      chunk<=burst_length(remaining-chunk,source+4*chunk,destination+(MUTATION==4 ? chunk:4*chunk));state<=AR;
     end
    end
    default:;
   endcase
  end
 end
endmodule
