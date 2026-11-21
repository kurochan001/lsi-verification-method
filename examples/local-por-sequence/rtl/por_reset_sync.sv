// Reset synchroniser: asserts asynchronously when the detector output falls, releases on a clock edge.
// MUTATION 1: releases one stage early. 2: follows the detector directly. 3: clears on the clock only.
module por_reset_sync #(parameter STAGES = 2, MUTATION = 0)(
    input  wire clk,
    input  wire pwr_ok,
    output wire rst_n
);
    localparam TAP = (MUTATION == 1) ? STAGES - 2 : STAGES - 1;
    reg [STAGES-1:0] chain;
    generate
        if (MUTATION == 3) begin : g_clocked_clear
            always @(posedge clk)
                if (!pwr_ok) chain <= {STAGES{1'b0}};
                else chain <= {chain[STAGES-2:0], 1'b1};
        end else begin : g_async_clear
            always @(posedge clk or negedge pwr_ok)
                if (!pwr_ok) chain <= {STAGES{1'b0}};
                else chain <= {chain[STAGES-2:0], 1'b1};
        end
    endgenerate
    assign rst_n = (MUTATION == 2) ? pwr_ok : chain[TAP];
endmodule
