// Switched domain A: an accumulator that is retained, and two registers that are not.
// MUTATION 4: scratch has no reset, so it is not initialized after power-up.
module pd_domain_a #(parameter MUTATION = 0) (
    input  wire       clk,
    input  wire       rst_n,      // reset of this domain
    input  wire       op,         // accept one operand
    input  wire [7:0] data,
    input  wire       restore,    // load the retained value
    input  wire [7:0] acc_saved,
    output wire [7:0] sum,
    output wire       idle_n,
    output wire [7:0] last
);
    reg [7:0] acc;
    reg [7:0] scratch;
    reg       fired;

    assign sum    = acc;
    assign idle_n = ~fired;
    assign last   = scratch;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc   <= 8'd0;
            fired <= 1'b0;
        end else begin
            fired <= op;
            if (restore) acc <= acc_saved;
            else if (op) acc <= acc + data;
        end
    end

    generate
        if (MUTATION == 4) begin : g_no_reset
            always @(posedge clk) if (rst_n && op) scratch <= data;
        end else begin : g_reset
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) scratch <= 8'd0;
                else if (op) scratch <= data;
            end
        end
    endgenerate
endmodule
