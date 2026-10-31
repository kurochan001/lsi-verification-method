module implicit(input wire a,output wire q);
  assign misspelled_net=a;
  assign q=misspelled_net;
endmodule
