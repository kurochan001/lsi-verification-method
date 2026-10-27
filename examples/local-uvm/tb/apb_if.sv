interface apb_if(input bit clk);
 logic rst_n=0,psel=0,penable=0,pwrite=0;
 logic [7:0] paddr=0;logic [31:0] pwdata=0;logic [3:0] events=0;
 wire pready,pslverr;wire [31:0] prdata,config_value;wire [3:0] pending;
endinterface
