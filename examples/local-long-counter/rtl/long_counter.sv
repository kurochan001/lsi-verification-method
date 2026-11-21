// Up counter with a programmable limit, as used for a long timer.
//
// Priority on each rising clock edge: reset, clear, test load, count.
//   count step : the counter returns to 0 and tick pulses for one cycle when count == limit,
//                otherwise it adds 1 modulo 2**WIDTH.
//   test load  : test_mode && test_load copies test_value into the counter. It is the path a
//                test uses to start near a carry that would take hours to reach by counting.
//
// When WIDTH > SPLIT the carry chain is cut at bit SPLIT: the lower SPLIT bits add 1 on their
// own, and a registered flag (carry_q) tells the upper part that the lower part is all ones.
// When the upper part is wider than 8 bits it is cut once more, 8 bits above SPLIT.
// When WIDTH <= SPLIT there is one adder and none of that logic exists.
//
// MUTATION: 1 no return to 0 at the limit, 2 tick without enable, 3 the second cut of the
// upper part misses one bit, 4 the limit comparison ignores the top bit, 5 the test load does
// not update carry_q, 6 carry_q follows the lower part while the counter is paused.
// Mutations 3 to 6 change logic that exists only when WIDTH > SPLIT (3: WIDTH > SPLIT + 8).
module long_counter #(
    parameter WIDTH = 32,
    parameter SPLIT = 16,
    parameter MUTATION = 0
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             enable,
    input  logic             clear,
    input  logic [WIDTH-1:0] limit,
    input  logic             test_mode,
    input  logic             test_load,
    input  logic [WIDTH-1:0] test_value,
    output logic [WIDTH-1:0] count,
    output logic             tick
);
    logic             load;
    logic             match;
    logic [WIDTH-1:0] next;     // count + 1, as this implementation computes it
    logic [WIDTH-1:0] count_d;

    assign load = test_mode && test_load;

    always_comb begin
        count_d = count;
        if (!rst_n || clear) count_d = '0;
        else if (load) count_d = test_value;
        else if (enable) count_d = (match && MUTATION != 1) ? '0 : next;
    end

    always_ff @(posedge clk) begin
        count <= count_d;
        tick  <= rst_n && !clear && !load && match && (enable || MUTATION == 2);
    end

    generate
        if (WIDTH <= SPLIT) begin : g_single
            assign match = count == limit;
            assign next  = count + 1'b1;
        end else begin : g_split
            localparam HW = WIDTH - SPLIT;
            logic            carry_q;   // the lower part is all ones
            logic [HW-1:0]   high;
            logic [HW-1:0]   high_next;
            logic [HW-1:0]   high_diff;
            logic [SPLIT-1:0] low_next;

            assign high      = count[WIDTH-1:SPLIT];
            assign low_next  = count[SPLIT-1:0] + 1'b1;
            assign high_diff = high ^ limit[WIDTH-1:SPLIT];
            assign match     = count[SPLIT-1:0] == limit[SPLIT-1:0] &&
                               (MUTATION == 4 ? high_diff[HW-2:0] == '0 : high_diff == '0);
            assign next      = {carry_q ? high_next : high, low_next};

            if (HW <= 8) begin : g_one
                assign high_next = high + 1'b1;
            end else begin : g_two
                logic stage;   // the 8 bits above the cut are all ones
                assign stage     = MUTATION == 3 ? &high[6:0] : &high[7:0];
                assign high_next = {high[HW-1:8] + {{(HW-9){1'b0}}, stage}, high[7:0] + 1'b1};
            end

            always_ff @(posedge clk) begin
                if (!rst_n || clear || (load && MUTATION != 5) || (enable && !load))
                    carry_q <= &count_d[SPLIT-1:0];
                else if (MUTATION == 6 && !load)
                    carry_q <= &low_next;
            end
`ifdef FORMAL
            // The flag and the bits it summarizes. A proof by induction starts from any state,
            // so it needs this relation; a test that forces count alone breaks it.
            // Checked from the second cycle on: the harness holds reset in the first one.
            reg f_past = 0;
            always @(posedge clk) begin
                f_past <= 1;
                if (f_past) ai_carry: assert(carry_q == &count[SPLIT-1:0]);
            end
`endif
        end
    endgenerate
endmodule
