module latch(input wire en,d,output reg q);
  always @* if(en)q=d;
endmodule
