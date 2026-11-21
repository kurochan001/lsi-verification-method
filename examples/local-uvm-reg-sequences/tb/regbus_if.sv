interface regbus_if(input bit clk);
 logic rst_n=0,psel=0,penable=0,pwrite=0;
 logic [7:0] paddr=0;logic [31:0] pwdata=0;logic [3:0] events=0;
 wire pready,pslverr;wire [31:0] prdata;
 // Observation and deposit points for the user-defined backdoor. They are testbench
 // connections to the selected DUT instance and do not use the UVM HDL DPI routines.
 wire [7:0] peek_ctrl;wire [31:0] peek_scratch;
 logic poke=0;logic poke_target=0;logic [31:0] poke_value=0;
endinterface
