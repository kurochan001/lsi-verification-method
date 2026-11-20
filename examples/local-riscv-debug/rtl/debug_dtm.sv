// Debug transport module on the TAP of local-jtag-tap: two data registers, dtmcs and dmi.
// The TAP has a four-bit instruction register, so the instructions are 4'b1000 (dtmcs) and
// 4'b1001 (dmi), not the five-bit 0x10 and 0x11 of the specification. dmi is 41 bits: address
// (7), data (32), operation (2: 0 nothing, 1 read, 2 write). Update-DR with an operation starts
// a request; Capture-DR returns the address, the data of the last read and status 0. The debug
// module answers long before the next capture (TCK is derived from its clock and at least four
// times slower), so the status never says busy. dtmcs is read-only: version 1, seven address bits.
module debug_dtm #(parameter IDCODE = 32'h12345679) (
    input  wire        tck, tms, tdi, trst_n,
    output wire        tdo,
    output reg         dmi_req,      // toggles for every request
    output reg  [1:0]  dmi_op,
    output reg  [6:0]  dmi_addr,
    output reg  [31:0] dmi_wdata,
    input  wire [31:0] dmi_rdata);
    localparam [3:0] DTMCS = 4'b1000, DMI = 4'b1001;
    localparam [31:0] DTMCS_VALUE = 32'h00001071;  // idle 1, dmistat 0, abits 7, version 1
    wire [14:0] tap_out;
    wire [3:0] ir = tap_out[11:8];
    wire capture = tap_out[12], shift = tap_out[13], update = tap_out[14];
    wire select = ir == DTMCS || ir == DMI;
    reg [40:0] sr;
    jtag_tap #(.IDCODE(IDCODE), .EXT(1)) tap(.tck(tck), .tms(tms), .tdi(tdi), .trst_n(trst_n),
        .pin_in({select, sr[0], 8'd0}), .tdo(tdo), .pin_out(tap_out));
    always @(posedge tck or negedge trst_n) begin
        if (!trst_n) begin
            sr <= 0; dmi_req <= 0; dmi_op <= 0; dmi_addr <= 0; dmi_wdata <= 0;
        end else begin
            if (capture && ir == DTMCS) sr <= {9'd0, DTMCS_VALUE};
            if (capture && ir == DMI) sr <= {dmi_addr, dmi_rdata, 2'b00};
            // dtmcs shifts through its low 32 bits, dmi through all 41.
            if (shift && ir == DTMCS) sr <= {9'd0, tdi, sr[31:1]};
            if (shift && ir == DMI) sr <= {tdi, sr[40:1]};
            if (update && ir == DMI && sr[1:0] != 2'd0) begin
                dmi_addr <= sr[40:34]; dmi_wdata <= sr[33:2]; dmi_op <= sr[1:0]; dmi_req <= !dmi_req;
            end
        end
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire pins_unused = &{1'b0, tap_out[7:0]};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
