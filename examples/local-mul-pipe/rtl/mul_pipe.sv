module mul_pipe #(parameter STAGES=3, MUTATION=0)(
    input wire clk, rst_n,
    input wire vin,
    input wire [7:0] a, b,
    output reg vld,
    output reg [15:0] out
);
    // Stage 1 registers the two partial products, stage 2 adds them,
    // stage 3 registers the answer. STAGES=2 merges stages 1 and 2.
    wire [11:0] pp_lo = a[3:0] * b;
    wire [3:0] upper_digit = MUTATION == 3 ? a[3:0] : a[7:4];
    wire [11:0] pp_hi = upper_digit * b;
    reg [11:0] plo_r, phi_r;
    reg [15:0] sum_r;
    reg v1, v2;
    wire [11:0] lo = STAGES == 3 ? plo_r : pp_lo;
    wire [11:0] hi = STAGES == 3 ? phi_r : pp_hi;
    wire [15:0] aligned_hi = MUTATION == 1 ? {4'b0, hi} : {hi, 4'b0};
    wire [15:0] sum_final = sum_r;
    wire v_final = STAGES == 3 ? v2 : v1;
    wire v_pipe = MUTATION == 2 ? (STAGES == 3 ? v1 : vin) : v_final;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            plo_r <= 0; phi_r <= 0; sum_r <= 0;
            v1 <= 0; v2 <= 0; vld <= 0; out <= 0;
        end else begin
            plo_r <= pp_lo; phi_r <= pp_hi;
            sum_r <= {4'b0, lo} + aligned_hi;
            v1 <= vin;
            v2 <= v1;
            vld <= v_pipe;
            out <= MUTATION == 4 ? {8'b0, sum_final[7:0]} : sum_final;
        end
    end
endmodule
