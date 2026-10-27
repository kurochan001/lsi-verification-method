// Word-line direct mapped write-back cache + serialized bypass DMA port.
// Commands 1 CPU read,2 CPU write,3 clean,4 invalidate,5 DMA read,6 DMA write.
module cache_dma #(parameter MUTATION=0,LINES=2,LATENCY=1)(
 input wire clk,rst_n,req_valid,input wire [2:0] req_op,input wire [3:0] req_addr,input wire [31:0] req_data,input wire [3:0] req_strb,
 output wire req_ready,output reg rsp_valid,input wire rsp_ready,output reg rsp_error,output reg [31:0] rsp_data,
 input wire [3:0] debug_addr,output wire [31:0] debug_data
);
 reg [31:0] memory[0:15],data[0:LINES-1];reg [3:0] tag[0:LINES-1];reg valid[0:LINES-1],dirty[0:LINES-1];
 reg busy;integer remaining,index;reg [2:0] operation;reg [3:0] address;reg [31:0] payload;reg [3:0] strobe;
 function [31:0] merge_bytes(input [31:0] old_value,new_value,input [3:0] enable);
 begin for(integer i=0;i<4;i=i+1)merge_bytes[8*i+:8]=enable[i] ? new_value[8*i+:8]:old_value[8*i+:8];end endfunction
 assign req_ready=rst_n && !busy && !rsp_valid;assign debug_data=memory[debug_addr];
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 busy<=0;remaining<=0;operation<=0;address<=0;payload<=0;strobe<=0;rsp_valid<=0;rsp_error<=0;rsp_data<=0;
 for(integer i=0;i<16;i=i+1)memory[i]<=0;
 for(integer i=0;i<LINES;i=i+1)begin data[i]<=0;tag[i]<=0;valid[i]<=0;dirty[i]<=0;end
 end else begin
 if(rsp_valid && rsp_ready)rsp_valid<=0;
 if(req_valid && req_ready)begin busy<=1;remaining<=LATENCY;operation<=req_op;address<=req_addr;payload<=req_data;strobe<=req_strb;end
 if(busy)begin
 if(remaining!=0)remaining<=remaining-1;
 else begin
 busy<=0;rsp_valid<=1;rsp_error<=0;rsp_data<=0;index=address%LINES;
 case(operation)
 1,2:begin
 if(!valid[index] || (tag[index]!=address && MUTATION!=3))begin
 if(valid[index] && dirty[index] && MUTATION!=1)memory[tag[index]]<=data[index];
 tag[index]<=address;valid[index]<=1;dirty[index]<=operation==2;
 data[index]<=operation==2 ? merge_bytes(memory[address],payload,strobe):memory[address];
 if(operation==1)rsp_data<=memory[address];
 end else if(operation==2)begin data[index]<=merge_bytes(data[index],payload,strobe);dirty[index]<=1;end
 else rsp_data<=data[index];
 end
 3:if(valid[index] && tag[index]==address && dirty[index])begin
 if(MUTATION!=1)memory[address]<=data[index];dirty[index]<=0;
 end
 4:if(valid[index] && tag[index]==address)begin
 // Invalidate of a dirty line is rejected to prevent silent data loss.
 if(dirty[index])rsp_error<=1;else if(MUTATION!=2)valid[index]<=0;
 end
 5:rsp_data<=memory[address];
 6:if(MUTATION!=4)memory[address]<=merge_bytes(memory[address],payload,strobe);
 default:rsp_error<=1;
 endcase
 end end
 end end
endmodule
