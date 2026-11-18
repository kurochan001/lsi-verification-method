// Two symmetric read/write ports. Effective same-word dual writes are rejected.
module ram_tdp #(parameter DATA_W=32,DEPTH=16,RDW_MODE=0,MUTATION=0)(
    input wire clk,rst_n,a_en,a_write,b_en,b_write,
    input wire [$clog2(DEPTH)-1:0] a_addr,b_addr,
    input wire [DATA_W-1:0] a_wdata,b_wdata,
    input wire [DATA_W/8-1:0] a_mask,b_mask,
    output reg [DATA_W-1:0] a_rdata,b_rdata,
    output wire write_conflict
);
    reg [DATA_W-1:0] memory[0:DEPTH-1];
    wire a_effective=a_en && a_write && (|a_mask);
    wire b_effective=b_en && b_write && (|b_mask);
    assign write_conflict=MUTATION!=10 && a_effective && b_effective && a_addr==b_addr;
    wire a_rdw=b_effective && a_addr==b_addr;
    wire b_rdw=a_effective && a_addr==b_addr;
    function automatic [DATA_W-1:0] merged(input [DATA_W-1:0] old_word,new_word,input [DATA_W/8-1:0] mask);
        reg [DATA_W-1:0] value;
        begin
            value=old_word;
            for (integer lane=0;lane<DATA_W/8;lane=lane+1)
                if (mask[lane]) value[lane*8+:8]=new_word[lane*8+:8];
            merged=value;
        end
    endfunction
    always @(posedge clk) begin
        if (!rst_n) begin a_rdata<=0;b_rdata<=0;end
        else begin
            if (!write_conflict) begin
                if (a_en && a_write) begin
                    for (integer lane=0;lane<DATA_W/8;lane=lane+1)
                        if (a_mask[lane] || MUTATION==8) memory[a_addr][lane*8+:8]<=a_wdata[lane*8+:8];
                end
                if (b_en && b_write) begin
                    for (integer lane=0;lane<DATA_W/8;lane=lane+1)
                        if (b_mask[lane] || MUTATION==8) memory[b_addr][lane*8+:8]<=b_wdata[lane*8+:8];
                end
            end
            if (a_en && !a_write && !(a_rdw && RDW_MODE==2))
                a_rdata<=a_rdw && RDW_MODE==1 && MUTATION!=9 ? merged(memory[a_addr],b_wdata,b_mask):memory[a_addr];
            if (b_en && !b_write && !(b_rdw && RDW_MODE==2))
                b_rdata<=b_rdw && RDW_MODE==1 && MUTATION!=9 ? merged(memory[b_addr],a_wdata,a_mask):memory[b_addr];
        end
    end
endmodule
