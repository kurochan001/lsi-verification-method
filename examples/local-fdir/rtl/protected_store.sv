// Byte SECDED RAM; foreground write > foreground repair > background scrub.
// Verification fault masks are applied AFTER that edge's functional update.
module protected_store #(parameter DEPTH=4)(
    input wire clk,rst_n,write_en,read_en,scrub_en,
    input wire [$clog2(DEPTH)-1:0] addr,inject_addr,input wire [7:0] write_data,
    input wire inject_en,input wire [12:0] inject_mask,
    output wire [7:0] read_data,output wire corrected,uncorrectable,
    output reg [$clog2(DEPTH)-1:0] scrub_addr,output reg scrub_corrected,scrub_uncorrectable
);
    reg [12:0] memory[0:DEPTH-1];
    wire [12:0] encoded,read_fixed,scrub_fixed,unused_encoded;
    wire read_c,read_u,scrub_c,scrub_u;wire [7:0] scrub_data;
    secded foreground(.data_in(write_data),.received(memory[addr]),.encoded(encoded),.corrected_code(read_fixed),.data_out(read_data),.corrected(read_c),.uncorrectable(read_u));
    secded background(.data_in(8'd0),.received(memory[scrub_addr]),.encoded(unused_encoded),.corrected_code(scrub_fixed),.data_out(scrub_data),.corrected(scrub_c),.uncorrectable(scrub_u));
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_scrub_data=&{1'b0,scrub_data,unused_encoded};
    /* verilator lint_on UNUSEDSIGNAL */
    assign corrected=read_en && read_c;assign uncorrectable=read_en && read_u;
    for(genvar i=0;i<DEPTH;i=i+1)begin:words
        wire [12:0] fault_mask=inject_en && int'(inject_addr)==i ? inject_mask : 13'd0;
        always @(posedge clk)begin
            if(!rst_n)memory[i]<=0;
            else if(write_en && int'(addr)==i)memory[i]<=encoded^fault_mask;
            else if(corrected && int'(addr)==i)memory[i]<=read_fixed^fault_mask;
            else if(scrub_en && scrub_c && int'(scrub_addr)==i)memory[i]<=scrub_fixed^fault_mask;
            else memory[i]<=memory[i]^fault_mask;
        end
    end
    always @(posedge clk)begin
        if(!rst_n)begin scrub_addr<=0;scrub_corrected<=0;scrub_uncorrectable<=0;end
        else begin
            scrub_corrected<=scrub_en && scrub_c;scrub_uncorrectable<=scrub_en && scrub_u;
            if(scrub_en)scrub_addr<=int'(scrub_addr)==DEPTH-1 ? 0 : scrub_addr+1'b1;
        end
    end
endmodule
