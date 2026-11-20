// Switched domain B: a mode that is retained and a counter that is not. The counter also adds
// bit 0 of the sum of domain A, so B may only be on while A is on.
// MUTATION 3: the retained mode is not loaded on restore.
module pd_domain_b #(parameter MUTATION = 0) (
    input  wire       clk,
    input  wire       rst_n,      // reset of this domain
    input  wire       op,
    input  wire [7:0] data,       // bit 7 set: write the mode; clear: add to the counter
    input  wire       a_bit,      // from domain A, not isolated
    input  wire       restore,
    input  wire [3:0] mode_saved,
    output wire [7:0] count_out,
    output wire [3:0] mode_out
);
    reg [3:0] mode;
    reg [7:0] count;

    assign count_out = count;
    assign mode_out  = mode;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mode  <= 4'd0;
            count <= 8'd0;
        end else begin
            if (restore && MUTATION != 3) mode <= mode_saved;
            else if (op && data[7]) mode <= data[3:0];
            if (op && !data[7]) count <= count + {1'b0, data[6:0]} + {7'd0, a_bit};
        end
    end
endmodule
