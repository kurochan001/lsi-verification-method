// Successive-approximation control for a charge-redistribution ADC.
//
// A conversion is one sample cycle followed by BITS trial cycles, most significant bit first.
// In a trial cycle dac_code carries the bits kept so far plus the bit under test; the comparator
// answer is taken at the clock edge that ends the cycle (cmp = 1 keeps the bit).  The cycle after
// the last trial raises done for one clock with the final code on result.
//
// start is taken only while start_ready is 1 (idle, or the done cycle).  A start that arrives
// during a conversion is ignored, not queued.
//
// MUTATION selects one deliberate error for the negative tests (0 = correct circuit).
module sar_logic #(parameter BITS = 6, MUTATION = 0)(
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,
    input  wire            cmp,
    output wire            start_ready,
    output reg             sample,
    output reg  [BITS-1:0] dac_code,
    output reg             busy,
    output reg             done,
    output reg  [BITS-1:0] result
);
    localparam [BITS-1:0] MSB = {1'b1, {(BITS-1){1'b0}}};
    localparam [BITS-1:0] LSB = {{(BITS-1){1'b0}}, 1'b1};

    reg [BITS-1:0] mask;  // the bit under test, one-hot; zero outside the trial cycles
    reg [BITS-1:0] acc;   // bits kept so far
    reg [BITS-1:0] late;  // only used by mutation 6

    assign start_ready = !busy || MUTATION == 5;
    wire accept = start && start_ready;

    wire            keep  = MUTATION == 3 ? !cmp : cmp;
    wire [BITS-1:0] kept  = keep ? (acc | mask) : acc;
    wire [BITS-1:0] first = MUTATION == 1 ? LSB : MSB;
    wire [BITS-1:0] next  = MUTATION == 1 ? {mask[BITS-2:0], 1'b0} : {1'b0, mask[BITS-1:1]};
    wire            last  = MUTATION == 1 ? mask[BITS-1] : MUTATION == 2 ? mask[1] : mask[0];

    always @(posedge clk) begin
        if (!rst_n) begin
            sample   <= 1'b0;
            dac_code <= {BITS{1'b0}};
            busy     <= MUTATION == 7 ? busy : 1'b0;
            done     <= 1'b0;
            result   <= {BITS{1'b0}};
            mask     <= {BITS{1'b0}};
            acc      <= {BITS{1'b0}};
            late     <= {BITS{1'b0}};
        end else begin
            done <= 1'b0;
            late <= kept;
            if (MUTATION == 6 && done) result <= late;
            if (accept) begin
                busy     <= 1'b1;
                sample   <= 1'b1;
                mask     <= {BITS{1'b0}};
                acc      <= MUTATION == 4 ? result : {BITS{1'b0}};
                dac_code <= {BITS{1'b0}};
            end else if (sample) begin
                sample   <= 1'b0;
                mask     <= first;
                dac_code <= acc | first;
            end else if (busy && mask != {BITS{1'b0}}) begin
                if (last) begin
                    mask     <= {BITS{1'b0}};
                    busy     <= 1'b0;
                    done     <= 1'b1;
                    dac_code <= {BITS{1'b0}};
                    acc      <= {BITS{1'b0}};
                    if (MUTATION != 6) result <= kept;
                end else begin
                    acc      <= kept;
                    mask     <= next;
                    dac_code <= kept | next;
                end
            end
        end
    end
endmodule
