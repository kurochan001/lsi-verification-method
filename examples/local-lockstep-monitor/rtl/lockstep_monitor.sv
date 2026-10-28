module lockstep_monitor #(parameter FAULT_BIT=0, MUTATION=0)(
    input wire clk, rst_n,
    input wire op_valid,
    input wire [1:0] op,
    input wire [7:0] operand,
    input wire fault_inject,
    input wire recover,
    output reg [7:0] result,
    output reg error,
    output reg safe,
    output reg [1:0] error_code,
    output reg done
);
    localparam ADD=2'b00, XOR=2'b01, LOAD=2'b10, ILLEGAL=2'b11;
    reg [7:0] acc0, acc1;
    reg [7:0] next0, next1;
    wire [7:0] fault_mask = 8'h1 << FAULT_BIT;
    wire mismatch = MUTATION == 1 ? (((next0 ^ next1) & ~fault_mask) != 0) : (next0 != next1);

    always @* begin
        case (op)
            ADD: next0 = acc0 + operand;
            XOR: next0 = acc0 ^ operand;
            LOAD: next0 = operand;
            default: next0 = acc0;
        endcase
        case (op)
            ADD: next1 = acc1 + operand;
            XOR: next1 = acc1 ^ operand;
            LOAD: next1 = operand;
            default: next1 = acc1;
        endcase
        if (fault_inject) next1 = next1 ^ fault_mask;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc0 <= 0; acc1 <= 0; result <= 0; error <= 0; safe <= 0;
            error_code <= 0; done <= 0;
        end else begin
            done <= 0;
            if (recover && error) begin
                acc1 <= acc0; error <= 0; safe <= 0; error_code <= 0;
                result <= MUTATION == 3 ? (acc0 ^ 8'h01) : acc0;
            end else if (op_valid && !safe) begin
                done <= 1;
                if (op == ILLEGAL && MUTATION != 4) begin
                    error <= 1; safe <= 1; error_code <= 2; result <= 0;
                end else if (mismatch) begin
                    error <= 1; error_code <= 1;
                    if (MUTATION == 2) begin safe <= 0; result <= next0; end
                    else begin safe <= 1; result <= 0; end
                end else begin
                    acc0 <= next0; acc1 <= next1; result <= next0;
                end
            end
        end
    end
endmodule
