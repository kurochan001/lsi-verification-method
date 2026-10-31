module leaf(input wire a,b,output wire q);
  assign q=a&b;
endmodule
module unconnected(input wire a,output wire q);
  leaf u(.a(a),.q(q));
endmodule
