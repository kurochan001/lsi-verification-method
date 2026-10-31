// Byte request source: a request remains stable until the receiver accepts it.
module request_source #(parameter MUTATION=0)(
  input wire clk,rst_n,issue,input wire [7:0] value,input wire ready,
  output reg valid,output reg [7:0] data
);
  always @(posedge clk)begin
    if(!rst_n)begin valid<=0;data<=0;end
    else if(!valid || ready)begin valid<=issue;if(issue)data<=value;end
    else if(MUTATION==1)data<=data^8'h01;
  end
endmodule

// Capture at the beginning of a request, accept on the following edge.
// Correctness requires the source to keep valid/data stable while ready=0.
module request_sink #(parameter MUTATION=0)(
  input wire clk,rst_n,valid,input wire [7:0] data,
  output wire ready,output reg done,output reg [7:0] result
);
  reg pending;reg [7:0] captured;
  assign ready=pending;
  always @(posedge clk)begin
    if(!rst_n)begin pending<=0;done<=0;captured<=0;result<=0;end
    else begin
      done<=0;
      if(!pending && valid)begin captured<=data;pending<=1;end
      else if(pending)begin
        pending<=0;
        if(valid)begin done<=1;result<=captured^(MUTATION==2 ? 8'ha4:8'ha5);end
      end
    end
  end
endmodule
