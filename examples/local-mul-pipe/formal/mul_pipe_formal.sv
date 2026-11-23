// Proof harness: a reference product chain built only from the design's ports.
// Reset is constrained to stay released after the start (reset behaviour,
// including a mid-run reset, is checked in simulation). ap_product is the
// whole claim: every output word is the plain product from three cycles earlier.
module mul_pipe_formal(input wire clk, rst_n, vin, input wire [7:0] a, b);
    wire vld;
    wire [15:0] out;
    mul_pipe #(.STAGES(3)) dut(.*);
    reg f_past = 0;
    reg [15:0] p1 = 0, p2 = 0, p3 = 0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            p1 <= 0; p2 <= 0; p3 <= 0;
        end else begin
            p1 <= a * b; p2 <= p1; p3 <= p2;
        end
    end
    always @(posedge clk) begin
        f_past <= 1;
        if (!f_past) as_initial_reset: assume(!rst_n);
        // Keep reset released after the start: reset behaviour (including a mid-run
        // reset) is checked in simulation, and this proof focuses on the data path.
        if (f_past && $past(rst_n)) as_reset_stays: assume(rst_n);
        if (f_past) begin
            ap_product: assert(out == p3);
            cv_max: cover(vld && out == 16'hfe01);  // 255 * 255 reaches the output
            cv_one: cover(vld && out == 16'h0001);  // 1 * 1 reaches the output
        end
    end
endmodule
