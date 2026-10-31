module gain_pipe #(parameter int MUTATION=0)(
  input logic clk,rst_n,input_valid,output_ready,
  input logic [7:0] input_data,gain_before,write_gain,
  input logic gain_write,
  output logic input_ready,output_valid,
  output logic [7:0] output_data
);
  logic [15:0] product;
  assign input_ready=!output_valid || output_ready;
  assign product={8'b0,input_data} * {8'b0,((MUTATION==1 && gain_write) ? write_gain:gain_before)};
  always_ff @(posedge clk) begin
    if(!rst_n) begin
      if(MUTATION!=3) begin output_valid<=0;output_data<=0;end
    end else if(input_ready) begin
      output_valid<=input_valid;
      if(input_valid) output_data<=(MUTATION==2 || product<=255) ? product[7:0]:8'hff;
    end
  end
endmodule
