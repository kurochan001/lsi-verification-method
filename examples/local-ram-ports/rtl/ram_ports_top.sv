// KIND: 0=single port A, 1=A write/B read, 2=two symmetric read/write ports.
// Every request is acknowledged; illegal operations have no memory side effects.
module ram_ports_top #(
    parameter DATA_W=32,DEPTH=16,ADDR_W=16,BASE_ADDR=256,KIND=2,RDW_MODE=0,MUTATION=0
)(
    input wire clk,rst_n,
    input wire a_valid,a_write,a_word,b_valid,b_write,b_word,
    input wire [ADDR_W-1:0] a_addr,b_addr,
    input wire [DATA_W-1:0] a_wdata,b_wdata,
    input wire [DATA_W/8-1:0] a_strb,b_strb,
    output wire a_ready,b_ready,
    output reg a_rsp_valid,b_rsp_valid,a_error,b_error,write_collision,a_read_collision,b_read_collision,
    output wire [DATA_W-1:0] a_rdata,b_rdata
);
    localparam AW=$clog2(DEPTH);
    wire [AW-1:0] a_index,b_index;
    wire [DATA_W/8-1:0] a_mask,b_mask;
    wire a_address_error,b_address_error;
    ram_address_adapter #(.DATA_W(DATA_W),.DEPTH(DEPTH),.ADDR_W(ADDR_W),.BASE_ADDR(BASE_ADDR),.MUTATION(MUTATION))
        adapt_a(a_word,a_addr,a_strb,a_index,a_mask,a_address_error),
        adapt_b(b_word,b_addr,b_strb,b_index,b_mask,b_address_error);
    wire a_capable=KIND!=1 || a_write;
    wire b_capable=KIND==2 || (KIND==1 && !b_write);
    wire a_good=rst_n && a_valid && a_capable && (!a_address_error || (MUTATION==6 && a_write));
    wire b_good=rst_n && b_valid && b_capable && (!b_address_error || (MUTATION==6 && b_write));
    wire a_effective=a_good && a_write && (|a_mask);
    wire b_effective=b_good && b_write && (|b_mask);
    wire conflict;
    wire a_rdw=a_good && !a_write && b_effective && a_index==b_index;
    wire b_rdw=b_good && !b_write && a_effective && a_index==b_index;
    assign a_ready=rst_n;
    assign b_ready=rst_n;
    always @(posedge clk) begin
        if (!rst_n) begin
            a_rsp_valid<=0;b_rsp_valid<=0;a_error<=0;b_error<=0;
            write_collision<=0;a_read_collision<=0;b_read_collision<=0;
        end else begin
            a_rsp_valid<=a_valid;b_rsp_valid<=b_valid;
            a_error<=a_valid && (!a_capable || a_address_error || conflict);
            b_error<=b_valid && (!b_capable || b_address_error || conflict);
            write_collision<=conflict;a_read_collision<=a_rdw;b_read_collision<=b_rdw;
        end
    end
    generate if (KIND==0) begin: single_port
        ram_sp #(.DATA_W(DATA_W),.DEPTH(DEPTH),.MUTATION(MUTATION))
            ram(clk,rst_n,a_good,a_write,a_index,a_wdata,a_mask,a_rdata);
        assign b_rdata=0;assign conflict=0;
        wire unused_b=^{b_good,b_write,b_index,b_wdata,b_mask};
    end else if (KIND==1) begin: one_read_one_write
        ram_1r1w #(.DATA_W(DATA_W),.DEPTH(DEPTH),.RDW_MODE(RDW_MODE),.MUTATION(MUTATION))
            ram(clk,rst_n,a_good,b_good,a_index,b_index,a_wdata,a_mask,b_rdata);
        assign a_rdata=0;assign conflict=0;
        wire unused_b=^{b_wdata,b_mask};
    end else begin: true_dual_port
        ram_tdp #(.DATA_W(DATA_W),.DEPTH(DEPTH),.RDW_MODE(RDW_MODE),.MUTATION(MUTATION))
            ram(clk,rst_n,a_good,a_write,b_good,b_write,a_index,b_index,a_wdata,b_wdata,
                a_mask,b_mask,a_rdata,b_rdata,conflict);
    end endgenerate
endmodule
