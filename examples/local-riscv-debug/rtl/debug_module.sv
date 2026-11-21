// A debug module for one hart: dmcontrol, dmstatus, abstractcs, command and data0, as in the
// RISC-V Debug Specification 1.0 (sections 3.7.1 and 3.14; checked against its register tables). The only
// abstract command is Access Register with 32-bit registers. A command takes CMD_CYCLES clock
// cycles, as an implementation that runs instructions for it would; meanwhile abstractcs.busy
// is set and any use of command, data0 or abstractcs gives cmderr 1. Mutation 28 addresses the
// neighbouring general register; mutation 29 accepts writes while busy.
module debug_module #(parameter MUTATION = 0, CMD_CYCLES = 512) (
    input  wire        clk, rst_n,
    input  wire        dmi_req,              // from the transport: toggles for every request
    input  wire [1:0]  dmi_op,
    input  wire [6:0]  dmi_addr,
    input  wire [31:0] dmi_wdata,
    output reg  [31:0] dmi_rdata,
    output wire        haltreq,
    output reg         resumereq, reg_we,
    output wire [15:0] regno,
    output wire [31:0] reg_wdata,
    input  wire        halted, reg_known,
    input  wire [31:0] reg_rdata);
    localparam [6:0] DATA0 = 7'h04, DMCONTROL = 7'h10, DMSTATUS = 7'h11, ABSTRACTCS = 7'h16, COMMAND = 7'h17;
    reg seen, dmactive, haltreq_q, resumeack, resuming, busy;
    reg [2:0] cmderr;
    reg [31:0] data0;
    reg [16:0] command;          // write flag and register number of the command in progress
    reg [15:0] count;
    localparam [15:0] CYCLES = CMD_CYCLES[15:0];
    wire request = dmi_req != seen;
    wire read = request && dmi_op == 2'd1, write = request && dmi_op == 2'd2;
    assign haltreq = dmactive && haltreq_q;
    // Mutation 28: x(n) is read and written as x(n ^ 1).
    assign regno = MUTATION == 28 && command[15:5] == 11'h080 ? command[15:0] ^ 16'd1 : command[15:0];
    assign reg_wdata = data0;
    wire [31:0] dmstatus = {14'd0, {2{resumeack}}, 4'd0, {2{!halted}}, {2{halted}}, 1'b1, 3'd0, 4'd3};
    wire [31:0] abstractcs = {19'd0, busy, 1'b0, cmderr, 4'd0, 4'd1};
    wire guarded = dmi_addr == DATA0 || dmi_addr == COMMAND || dmi_addr == ABSTRACTCS;
    wire accept = !busy || MUTATION == 29;
    // What a new command would do: 0 start, otherwise the error it ends with at once.
    wire [31:0] c = dmi_wdata;
    wire unsupported = c[31:23] != 9'd0 || c[22:20] != 3'd2 || c[19] || c[18];  // bit 23 is reserved
    // The CSRs that the attached core (rv32i_core with TRAPS = 1) has but does not hand to the
    // debugger. A register the core has is "not supported" (cmderr 2); one it does not have at
    // all is an exception (cmderr 3), as the specification requires for Access Register.
    wire [11:0] csr = command[11:0];
    wire core_csr = command[15:12] == 4'h0 && (csr == 12'h300 || csr == 12'h304 || csr == 12'h305 ||
                    (csr >= 12'h340 && csr <= 12'h344));
    always @(posedge clk) begin
        if (!rst_n) begin
            seen <= 0; dmactive <= 0; haltreq_q <= 0; resumeack <= 0; resuming <= 0; busy <= 0; cmderr <= 0;
            data0 <= 0; command <= 0; count <= 0; dmi_rdata <= 0; resumereq <= 0; reg_we <= 0;
        end else begin
            seen <= dmi_req; resumereq <= 0; reg_we <= 0;
            if (resuming && !halted) begin resumeack <= 1; resuming <= 0; end
            if (busy) begin
                count <= count - 16'd1;
                if (count == 16'd1) begin
                    busy <= 0;
                    if (command[16]) reg_we <= 1; else data0 <= reg_rdata;
                end
            end
            if (read) case (dmi_addr)
                DATA0:      dmi_rdata <= data0;
                DMCONTROL:  dmi_rdata <= {31'd0, dmactive};   // haltreq and resumereq read as zero
                DMSTATUS:   dmi_rdata <= dmstatus;
                ABSTRACTCS: dmi_rdata <= abstractcs;
                default:    dmi_rdata <= 32'd0;     // command and everything else read as zero
            endcase
            if (request && guarded && !accept && cmderr == 3'd0 && !(read && dmi_addr != DATA0)) cmderr <= 3'd1;
            if (write && dmi_addr == DMCONTROL) begin
                dmactive <= dmi_wdata[0];
                if (!dmi_wdata[0]) begin  // inactive: the module returns to its reset state
                    haltreq_q <= 0; resumeack <= 0; resuming <= 0; busy <= 0; cmderr <= 0; data0 <= 0; command <= 0;
                end else begin
                    haltreq_q <= dmi_wdata[31];
                    // A resume request is ignored together with a halt request, and while running.
                    if (dmi_wdata[30] && !dmi_wdata[31] && halted) begin resumereq <= 1; resumeack <= 0; resuming <= 1; end
                end
            end
            if (write && dmi_addr == DATA0 && accept) data0 <= dmi_wdata;
            if (write && dmi_addr == ABSTRACTCS && accept) cmderr <= cmderr & ~dmi_wdata[10:8];
            // A command starts only while cmderr is 0. Checked in this order: the command is one
            // this module has, the hart is halted, the register is one the core has.
            if (write && dmi_addr == COMMAND && accept && cmderr == 3'd0) begin
                if (unsupported) cmderr <= 3'd2;
                else if (c[17]) begin
                    command <= c[16:0];
                    if (!halted) cmderr <= 3'd4;
                    else begin busy <= 1; count <= CYCLES; end
                end
            end
            // The register number is known one cycle after the command is taken.
            if (busy && count == CYCLES && !reg_known) begin busy <= 0; cmderr <= core_csr ? 3'd2 : 3'd3; end
        end
    end
endmodule
