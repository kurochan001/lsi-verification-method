// Boot verification block of the secure boot teaching SoC. On START it reads the image header
// from the boot flash itself, checks the magic, the payload length and the version against
// the one-time-programmable minimum, then streams the header and the payload into the SHA-256
// engine of local-sha256 and compares the digest with the one held in OTP. The verdict (PASS
// or FAIL with a reason) is sticky until reset: software can neither restart a finished check
// nor write the verdict. Everything the verdict unlocks is decided from these registers by
// hardware in secure_boot_soc. Mutations 1 to 3, 7 and 9 belong to this block.
module boot_ctrl #(parameter IMG_MAX = 112, MUTATION = 0) (
    input  wire         clk, rst_n,     // asynchronous: the verdict clears at once
    input  wire         engine_rst_n,   // synchronous reset of the SHA-256 engine
    input  wire         start,          // a write of 1 to CTRL
    input  wire         status_write,   // a write to STATUS (read-only: ignored)
    input  wire [31:0]  status_wdata,
    output wire [7:0]   flash_addr,     // word address in the boot flash
    input  wire [31:0]  flash_data,
    input  wire [255:0] otp_digest,
    input  wire [7:0]   otp_min_version,
    output wire         busy,
    output reg          pass, fail,
    output reg  [3:0]   reason,         // 1 magic, 2 length, 3 rollback, 4 digest
    output reg  [7:0]   plen,           // accepted payload length in bytes
    output reg  [7:0]   version
);
    localparam [2:0] IDLE = 0, HDR = 1, CMD = 2, FEED = 3, DIGEST = 4, DONE = 5;
    localparam [15:0] MAGIC = 16'hb007;
    localparam [7:0] MAX = IMG_MAX[7:0];
    reg [2:0] state;
    reg [6:0] index, total;

    wire [7:0] h_len = flash_data[7:0], h_ver = flash_data[15:8];
    wire bad_magic = flash_data[31:16] != MAGIC;
    wire bad_length = h_len == 8'd0 || h_len > MAX || (h_len[1:0] != 2'd0 && MUTATION != 2);
    wire too_old = MUTATION == 3 ? h_ver > otp_min_version : h_ver < otp_min_version;

    wire cmd_ready, byte_ready, digest_valid, engine_error;
    wire [255:0] digest;
    wire [7:0] byte_data = flash_data[{index[1:0], 3'b000} +: 8];
    // The header is word 0 of the flash and is hashed together with the payload.
    assign flash_addr = state == FEED ? {3'b000, index[6:2]} : 8'd0;
    assign busy = state != IDLE && state != DONE;

    sha256_engine #(.ROUNDS(1)) engine (
        .clk(clk), .rst_n(engine_rst_n), .cmd_valid(state == CMD), .length(total), .cmd_ready(cmd_ready),
        .byte_valid(state == FEED), .byte_data(byte_data), .byte_ready(byte_ready),
        .digest_valid(digest_valid), .digest_ready(state == DIGEST), .digest(digest), .error(engine_error));

    wire match = MUTATION == 1 ? digest[7:0] == otp_digest[7:0] : digest == otp_digest;

    // Mutation 9: the verdict has a power-up value but is not cleared by reset, so a PASS
    // survives a later reset (a register initialized like an FPGA flop, without its reset term).
    initial if (MUTATION == 9) pass = 1'b0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; index <= 0; total <= 0; fail <= 0; reason <= 0; plen <= 0; version <= 0;
            if (MUTATION != 9) pass <= 0;
        end else begin
            case (state)
                IDLE: if (start) state <= HDR;
                HDR: begin
                    if (bad_magic) begin fail <= 1; reason <= 4'd1; state <= DONE; end
                    else if (bad_length) begin fail <= 1; reason <= 4'd2; state <= DONE; end
                    else if (too_old) begin fail <= 1; reason <= 4'd3; state <= DONE; end
                    else begin
                        plen <= h_len; version <= h_ver; total <= h_len[6:0] + 7'd4; index <= 0; state <= CMD;
                    end
                end
                CMD: if (cmd_ready) state <= FEED;
                FEED: if (byte_ready) begin
                    index <= index + 7'd1;
                    if (index + 7'd1 == total) state <= DIGEST;
                end
                DIGEST: if (digest_valid) begin
                    if (match && !engine_error) pass <= 1;
                    else begin fail <= 1; reason <= 4'd4; end
                    state <= DONE;
                end
                default: state <= DONE;
            endcase
            // Mutation 7: STATUS is writable, so software can forge the verdict.
            if (MUTATION == 7 && status_write) begin pass <= status_wdata[1]; fail <= status_wdata[2]; end
        end
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = &{1'b0, status_wdata[31:3], status_wdata[0]};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
