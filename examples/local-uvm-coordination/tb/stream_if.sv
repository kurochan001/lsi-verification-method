`timescale 1ns/1ps
interface stream_if(input bit clk);
  bit recording=0;
  logic input_valid,input_ready,output_valid,output_ready;
  logic [7:0] input_data,output_data;
endinterface
