// Hand-written register block for the address map in ../registers.rdl.
// The formal properties are generated from that file; nothing here is generated.
module reg_block #(
    parameter MUTATION = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        psel,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [7:0]  paddr,
    input  wire [31:0] pwdata,
    input  wire [2:0]  events,
    output wire        pready,
    output wire        pslverr,
    output reg  [31:0] prdata
);
    reg        ctrl_enable;
    reg [2:0]  ctrl_mode;
    reg [3:0]  ctrl_rev;
    reg        ctrl_spare;      // stores bit 3 only in mutant 5
    reg        status_done;
    reg [1:0]  status_err;
    reg [31:0] limit_value;
    reg [31:0] id_value;

    wire       access = psel && penable;
    // Mutant 6 decodes four address bits only, so 0x10 selects the register at 0x00.
    wire [7:0] addr   = MUTATION == 6 ? {4'd0, paddr[3:0]} : paddr;
    wire       mapped = addr == 8'd0 || addr == 8'd4 || addr == 8'd8 || addr == 8'd12;
    wire       write  = access && pwrite && mapped;

    assign pready  = access;
    assign pslverr = access && !mapped;

    wire       clear_done = write && addr == 8'd4 && pwdata[0];
    wire [1:0] clear_err  = write && addr == 8'd4 ? pwdata[5:4] : 2'd0;

    always @* begin
        prdata = 32'd0;
        case (addr)
            8'd0:    prdata = {20'd0, ctrl_rev, 1'b0, ctrl_mode, MUTATION == 5 ? ctrl_spare : 1'b0, 2'd0, ctrl_enable};
            8'd4:    prdata = MUTATION == 8 ? {26'd0, status_err, 2'd0, status_done, 1'b0}
                                            : {26'd0, status_err, 3'd0, status_done};
            8'd8:    prdata = limit_value;
            8'd12:   prdata = id_value;
            default: prdata = 32'd0;
        endcase
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            ctrl_enable <= 1'b0;
            ctrl_mode   <= MUTATION == 1 ? 3'd4 : 3'd5;
            ctrl_rev    <= 4'h9;
            ctrl_spare  <= 1'b0;
            status_done <= 1'b0;
            status_err  <= 2'd0;
            limit_value <= 32'd0;
            id_value    <= 32'h5749_4445;
        end else begin
            if (write && addr == 8'd0) begin
                ctrl_enable <= pwdata[0];
                ctrl_mode   <= MUTATION == 2 ? {ctrl_mode[2], pwdata[5:4]} : pwdata[6:4];
                if (MUTATION == 3) ctrl_rev <= pwdata[11:8];
                if (MUTATION == 5) ctrl_spare <= pwdata[3];
            end
            // Events win over a clear in the same cycle (precedence = hw).
            if (MUTATION == 7) status_done <= (status_done | events[0]) & ~clear_done;
            else               status_done <= (status_done & ~clear_done) | events[0];
            if (MUTATION == 4 && write && addr == 8'd4) status_err <= pwdata[5:4] | events[2:1];
            else                                        status_err <= (status_err & ~clear_err) | events[2:1];
            if (write && addr == 8'd8) limit_value <= pwdata;
        end
    end
endmodule
