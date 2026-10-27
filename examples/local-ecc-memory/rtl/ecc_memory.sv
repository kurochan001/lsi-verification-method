module ecc_memory #(parameter MUTATION=0,DEPTH=4)(
 input wire clk,rst_n,wr_en,rd_en,scrub_en,inject_en,input wire [$clog2(DEPTH)-1:0] addr,inject_addr,
 input wire [7:0] wr_data,input wire [12:0] inject_mask,
 output wire [7:0] rd_data,output wire corrected,uncorrectable,
 output reg [$clog2(DEPTH)-1:0] scrub_addr,output reg scrub_corrected,scrub_uncorrectable
);
 reg [12:0] mem[0:DEPTH-1];wire [12:0] encoded,read_fixed,scrub_fixed;wire [7:0] scrub_data;
 wire [12:0] raw_read=mem[addr],raw_scrub=mem[scrub_addr];wire read_c,read_u,scrub_c,scrub_u;
 secded enc(.data_in(wr_data),.received(raw_read),.encoded(encoded),.corrected_code(read_fixed),.data_out(rd_data),.corrected(read_c),.uncorrectable(read_u));
 secded dec(.data_in(8'b0),.received(raw_scrub),.encoded(),.corrected_code(scrub_fixed),.data_out(scrub_data),.corrected(scrub_c),.uncorrectable(scrub_u));
 assign corrected=rd_en && read_c;assign uncorrectable=rd_en && read_u && MUTATION!=3;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 for(integer i=0;i<DEPTH;i=i+1)mem[i]<=0;
 scrub_addr<=0;scrub_corrected<=0;scrub_uncorrectable<=0;
 end else begin
 scrub_corrected<=0;scrub_uncorrectable<=0;
 // Lowest priority scrub, then foreground repair, foreground write, fault injection.
 if(scrub_en)begin
 scrub_corrected<=scrub_c;scrub_uncorrectable<=scrub_u;
 if(scrub_c && MUTATION!=1)mem[scrub_addr]<=scrub_fixed;
 scrub_addr<=scrub_addr==DEPTH-1 ? 0:scrub_addr+1'b1;
 end
 if(rd_en && read_c && MUTATION!=4)mem[addr]<=read_fixed;
 if(wr_en)mem[addr]<=encoded;
 if(MUTATION==2 && scrub_en && scrub_c)mem[scrub_addr]<=scrub_fixed;
 if(inject_en)mem[inject_addr]<=mem[inject_addr]^inject_mask;
 end end
endmodule
