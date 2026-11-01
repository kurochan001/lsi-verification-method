// Three replicas; update priority: reset, software write, voted repair, retention.
// Fault masks flip the resulting next state, including on write/repair edges.
module tmr_register #(parameter WIDTH=8,MUTATION=0)(
    input wire clk,rst_n,write_en,repair_en,
    input wire [WIDTH-1:0] write_data,fault0,fault1,fault2,
    output wire [WIDTH-1:0] voted,output wire disagreement,output reg repair_attempt
);
    reg [WIDTH-1:0] q0,q1,q2;
    wire [WIDTH-1:0] majority=(q0&q1)|(q0&q2)|(q1&q2);
    assign voted=MUTATION==1 ? q0|q1|q2 : majority;
    assign disagreement=MUTATION==4 ? 1'b0 : (q0!=q1 || q1!=q2);
    wire fixing=repair_en && disagreement && !write_en;
    wire [WIDTH-1:0] next_word=write_en && !(MUTATION==3 && repair_en && disagreement) ? write_data : majority;
    always @(posedge clk)begin
        if(!rst_n)begin q0<=0;q1<=0;q2<=0;repair_attempt<=0;end
        else begin
            repair_attempt<=fixing;
            if(write_en || (fixing && MUTATION!=2))begin
                q0<=next_word^fault0;q1<=next_word^fault1;q2<=next_word^fault2;
            end else begin q0<=q0^fault0;q1<=q1^fault1;q2<=q2^fault2;end
        end
    end
endmodule
