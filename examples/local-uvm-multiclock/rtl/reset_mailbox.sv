// Bundled-data mailbox model. Either endpoint reset flushes the channel.
// Local reset release is synchronized separately in the two clock domains.
module reset_mailbox #(parameter integer MUTATION=0)(
  input wire src_clk,dst_clk,src_rst_n,dst_rst_n,
  input wire src_valid,input wire [7:0] src_data,input wire [15:0] src_id,
  output wire src_ready,src_up,dst_up,
  input wire dst_ready,output wire dst_valid,
  output wire [7:0] dst_data,output wire [15:0] dst_id
);
  reg [1:0] src_release,dst_release,src_channel_release,dst_channel_release,req_sync,ack_sync,src_seen,dst_seen;
  reg req,ack,present;
  reg [7:0] held_data,result;
  reg [15:0] held_id,result_id;
  wire channel_rst_n=src_rst_n && dst_rst_n;
  wire sender_rst_n=MUTATION==4 ? channel_rst_n:src_channel_release[1];
  wire receiver_rst_n=MUTATION==2 ? dst_release[1]:MUTATION==4 ? channel_rst_n:dst_channel_release[1];
  assign src_up=MUTATION==3 ? src_rst_n:src_release[1];
  assign dst_up=dst_release[1];
  assign src_ready=channel_rst_n && sender_rst_n && src_up && (MUTATION==5 || dst_seen[1]) && !req && !ack_sync[1];
  assign dst_valid=channel_rst_n && receiver_rst_n && dst_up && src_seen[1] && present;
  assign dst_data=result ^ (MUTATION==1 ? 8'h01:8'h00);
  assign dst_id=result_id;
  always @(posedge src_clk or negedge src_rst_n)
    if(!src_rst_n)src_release<=0;else src_release<={src_release[0],1'b1};
  always @(posedge dst_clk or negedge dst_rst_n)
    if(!dst_rst_n)dst_release<=0;else dst_release<={dst_release[0],1'b1};
  always @(posedge src_clk or negedge channel_rst_n)
    if(!channel_rst_n)src_channel_release<=0;else src_channel_release<={src_channel_release[0],1'b1};
  always @(posedge dst_clk or negedge channel_rst_n)
    if(!channel_rst_n)dst_channel_release<=0;else dst_channel_release<={dst_channel_release[0],1'b1};
  always @(posedge src_clk or negedge sender_rst_n)begin
    if(!sender_rst_n)begin req<=0;held_data<=0;held_id<=0;ack_sync<=0;dst_seen<=0;end
    else begin
      ack_sync<={ack_sync[0],ack};dst_seen<={dst_seen[0],dst_up};
      if(ack_sync[1])req<=0;
      if(src_valid && src_ready)begin req<=1;held_data<=src_data;held_id<=src_id;end
    end
  end
  always @(posedge dst_clk or negedge receiver_rst_n)begin
    if(!receiver_rst_n)begin req_sync<=0;src_seen<=0;ack<=0;present<=0;result<=0;result_id<=0;end
    else begin
      req_sync<={req_sync[0],req};src_seen<={src_seen[0],src_up};
      if(!req_sync[1])ack<=0;
      if(req_sync[1] && !ack && !present)begin present<=1;result<=held_data^8'h3c;result_id<=held_id;end
      if(dst_valid && dst_ready)begin present<=0;ack<=1;end
    end
  end
endmodule
