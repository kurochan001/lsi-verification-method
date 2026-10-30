// Weight-stationary INT8 systolic array: c[col] = sum over row of a[row] * W[row][col].
// Row r of an accepted vector passes r skew registers, then moves right one PE per
// cycle while partial sums move down. Column c is delayed N-1-c more cycles, so all
// columns of one vector appear together 2N-2 edges after the vector is accepted.
module systolic_array #(parameter N=4, MUTATION=0)(
    input wire clk, rst_n,
    input wire w_valid, input wire [$clog2(N)-1:0] w_row, input wire [8*N-1:0] w_data,
    output wire w_ready,
    input wire a_valid, input wire [8*N-1:0] a_data, output wire a_ready,
    output wire c_valid, input wire c_ready, output wire [32*N-1:0] c_data);
    localparam SLOTS = 2*N-1;
    reg signed [7:0] weight [0:N*N-1];   // weight[r*N+c]
    reg signed [7:0] skew [0:N*N-1];     // skew[r*N+k], k < r
    reg signed [7:0] pe_a [0:N*N-1];     // activation leaving PE(r,c) to the right
    reg signed [31:0] pe_sum [0:N*N-1];  // partial sum leaving PE(r,c) downward
    reg signed [31:0] deskew [0:N*N-1];  // deskew[c*N+k], k < N-1-c
    reg [SLOTS-1:0] valid;
    wire stall = valid[SLOTS-1] && !c_ready;
    wire accept = a_valid && a_ready;
    assign c_valid = valid[SLOTS-1];
    assign w_ready = rst_n && valid == 0;
    assign a_ready = rst_n && !stall && !w_valid;
    genvar g;
    generate for (g = 0; g < N; g = g + 1) begin : column
        if (g == N-1) begin : direct
            assign c_data[32*g +: 32] = pe_sum[(N-1)*N + g];
        end else begin : delayed
            assign c_data[32*g +: 32] = deskew[g*N + N-2-g];
        end
    end endgenerate
    integer r, c, k, depth;
    reg signed [7:0] a_in;
    reg signed [31:0] sum_in, sum_out;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid <= 0;
            for (k = 0; k < N*N; k = k + 1) begin
                weight[k] <= 0; skew[k] <= 0; pe_a[k] <= 0; pe_sum[k] <= 0; deskew[k] <= 0;
            end
        end else begin
            if (w_valid && w_ready)
                for (c = 0; c < N; c = c + 1) weight[w_row*N + c] <= w_data[8*c +: 8];
            if (!stall || MUTATION == 3)
                for (c = 0; c < N-1; c = c + 1) begin
                    deskew[c*N] <= pe_sum[(N-1)*N + c];
                    for (k = 1; k < N-1-c; k = k + 1) deskew[c*N + k] <= deskew[c*N + k-1];
                end
            if (!stall) begin
                valid <= {valid[SLOTS-2:0], accept};
                for (r = 0; r < N; r = r + 1) begin
                    if (r > 0) skew[r*N] <= accept ? a_data[8*r +: 8] : 8'd0;
                    for (k = 1; k < r; k = k + 1) skew[r*N + k] <= skew[r*N + k-1];
                    depth = (MUTATION == 2 && r == N-1) ? r-1 : r;
                    for (c = 0; c < N; c = c + 1) begin
                        if (c > 0) a_in = pe_a[r*N + c-1];
                        else if (depth == 0) a_in = accept ? a_data[8*r +: 8] : 8'd0;
                        else a_in = skew[r*N + depth-1];
                        sum_in = r == 0 ? 32'sd0 : pe_sum[(r-1)*N + c];
                        if (MUTATION == 1) sum_out = sum_in + $unsigned(a_in) * $unsigned(weight[r*N + c]);
                        else sum_out = sum_in + a_in * weight[r*N + c];
                        pe_a[r*N + c] <= a_in;
                        pe_sum[r*N + c] <= MUTATION == 4 ? {{16{sum_out[15]}}, sum_out[15:0]} : sum_out;
                    end
                end
            end
        end
    end
endmodule
