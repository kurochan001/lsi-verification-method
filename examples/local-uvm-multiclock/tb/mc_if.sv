`timescale 1ps/1ps
interface mc_if(input bit src_clk,dst_clk);
  logic src_rst_n,dst_rst_n,src_valid,src_ready,src_up,dst_up,dst_valid,dst_ready;
  logic [7:0] src_data,dst_data;
  logic [15:0] src_id,dst_id;
endinterface
