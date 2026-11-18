// Separate write-only and read-only ports, on one common clock.
// RDW_MODE: 0=old word, 1=masked new word, 2=hold previous read output.
module ram_1r1w #(parameter DATA_W=32,DEPTH=16,RDW_MODE=0,MUTATION=0)(
    input wire clk,rst_n,we,re,
    input wire [$clog2(DEPTH)-1:0] waddr,raddr,
    input wire [DATA_W-1:0] wdata,input wire [DATA_W/8-1:0] byte_enable,
    output reg [DATA_W-1:0] rdata
);
    reg [DATA_W-1:0] memory[0:DEPTH-1];
    wire same_word=we && (|byte_enable) && waddr==raddr;
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
        if (!rst_n) rdata<=0;
        else begin
            if (we) begin
                for (integer lane=0;lane<DATA_W/8;lane=lane+1)
                    if (byte_enable[lane] || MUTATION==8) memory[waddr][lane*8+:8]<=wdata[lane*8+:8];
            end
            if (re && !(same_word && RDW_MODE==2))
                rdata<=same_word && RDW_MODE==1 && MUTATION!=9 ? merged(memory[raddr],wdata,byte_enable):memory[raddr];
        end
    end
endmodule
