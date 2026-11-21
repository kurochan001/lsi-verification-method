// Token bucket rate limiter. The level is kept in units of 1/2**FRAC token, so the refill
// rate can be a fraction of a token per clock. A grant costs one whole token.
//
// Every clock edge, in this order:
//   avail  = min(tokens + rate, cap)          cap = depth * 2**FRAC (the depth in whole tokens)
//   grant  = req and avail >= one token       (combinational output in the same cycle as req)
//   tokens = avail - (grant ? one token : 0)
// The refill is added before the saturation, and the saturation uses the depth of this cycle,
// so a smaller depth takes effect at once. Reset fills the bucket to the depth of that cycle.
//
// MUTATION (deliberate faults for the regression):
//   1 grants when the bucket is one unit short of a token (the level then wraps around)
//   2 the refill sum loses its carry (an adder as wide as the level)
//   3 saturates before adding the refill, so the bucket can exceed its depth by one refill
//   4 saturates with the depth of the previous cycle (a depth decrease takes effect late)
//   5 a cycle without a request still spends a token when one is available
module token_bucket #(parameter FRAC = 4, DEPTH_W = 4, RATE_W = 8, MUTATION = 0) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire [DEPTH_W-1:0]       depth,
    input  wire [RATE_W-1:0]        rate,
    input  wire                     req,
    output wire                     grant,
    output reg  [DEPTH_W+FRAC-1:0]  tokens
);
    localparam TW = DEPTH_W + FRAC;                       // level width: holds the largest depth
    localparam SW = (TW > RATE_W ? TW : RATE_W) + 1;      // sum width: level plus the largest refill
    localparam [SW-1:0] ONE = 1;
    localparam [SW-1:0] COST = ONE << FRAC;
    localparam [SW-1:0] COST_SHORT = COST - ONE;
    localparam [SW-1:0] LEVEL_MASK = (ONE << TW) - ONE;

    wire [TW-1:0] cap_level = {depth, {FRAC{1'b0}}};
    wire [SW-1:0] cap = {{(SW-TW){1'b0}}, cap_level};
    wire [SW-1:0] level = {{(SW-TW){1'b0}}, tokens};
    wire [SW-1:0] refill = {{(SW-RATE_W){1'b0}}, rate};
    reg  [SW-1:0] cap_q;                                  // depth of the previous cycle (mutation 4)

    wire [SW-1:0] full_sum = level + refill;
    wire [SW-1:0] sum = MUTATION == 2 ? (full_sum & LEVEL_MASK) : full_sum;
    wire [SW-1:0] limit = MUTATION == 4 ? cap_q : cap;
    wire [SW-1:0] clipped = level < limit ? level : limit;
    wire [SW-1:0] avail = MUTATION == 3 ? clipped + refill : (sum < limit ? sum : limit);
    wire          enough = avail >= (MUTATION == 1 ? COST_SHORT : COST);
    wire          spend = enough && (req || MUTATION == 5);
    wire [TW-1:0] next = TW'(avail - (spend ? COST : {SW{1'b0}}));

    assign grant = req && enough;

    always @(posedge clk) begin
        cap_q <= cap;
        if (!rst_n) tokens <= cap_level;
        else tokens <= next;
    end
endmodule
