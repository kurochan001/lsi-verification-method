// Always-on power controller for domains A and B. B needs A: B is on only while A is on.
// Down: save, isolate, reset, power off. Up: power on, wait SETTLE cycles in reset, release
// the reset, restore, release the isolation. One domain moves at a time and a started
// sequence always runs to its end.
// SETTLE is 1..15.
// MUTATION 5: A goes down while B is still on. 6: isolation only when the power is cut.
// MUTATION 7: the domain keeps accepting operations until it is isolated.
module pd_ctrl #(parameter MUTATION = 0, parameter SETTLE = 2) (
    input  wire clk,
    input  wire rst_n,
    input  wire req_a,
    input  wire req_b,
    output reg  pwr_a,
    output reg  pwr_b,
    output reg  iso_a,
    output reg  iso_b,
    output reg  rst_a_n,
    output reg  rst_b_n,
    output reg  act_a,
    output reg  act_b,
    output wire save_a,
    output wire save_b,
    output wire restore_a,
    output wire restore_b,
    output wire busy
);
    localparam [2:0] IDLE = 3'd0, SAVE = 3'd1, ISO = 3'd2, RST = 3'd3, OFF = 3'd4,
                     WAIT = 3'd5, RESTORE = 3'd6, REL = 3'd7;
    reg [2:0] phase;
    reg       sel;       // the domain that is moving: 0 = A, 1 = B
    reg [3:0] count;

    wire want_a = req_a;
    wire want_b = req_a & req_b;
    wire a_down_first = (MUTATION == 5) && act_a && !want_a;

    assign save_a    = (phase == SAVE) && !sel;
    assign save_b    = (phase == SAVE) && sel;
    assign restore_a = (phase == RESTORE) && !sel;
    assign restore_b = (phase == RESTORE) && sel;
    assign busy      = phase != IDLE;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pwr_a <= 1'b0; pwr_b <= 1'b0; iso_a <= 1'b1; iso_b <= 1'b1;
            rst_a_n <= 1'b0; rst_b_n <= 1'b0; act_a <= 1'b0; act_b <= 1'b0;
            phase <= IDLE; sel <= 1'b0; count <= 4'd0;
        end else begin
            case (phase)
                IDLE: begin
                    if (act_b && !want_b && !a_down_first) begin
                        sel <= 1'b1; phase <= SAVE;
                        if (MUTATION != 7) act_b <= 1'b0;
                    end else if (act_a && !want_a) begin
                        sel <= 1'b0; phase <= SAVE;
                        if (MUTATION != 7) act_a <= 1'b0;
                    end else if (!act_a && want_a) begin
                        sel <= 1'b0; pwr_a <= 1'b1; count <= SETTLE[3:0]; phase <= WAIT;
                    end else if (!act_b && want_b) begin
                        sel <= 1'b1; pwr_b <= 1'b1; count <= SETTLE[3:0]; phase <= WAIT;
                    end
                end
                SAVE: phase <= ISO;
                ISO: begin
                    if (MUTATION != 6) begin
                        if (sel) iso_b <= 1'b1; else iso_a <= 1'b1;
                    end
                    if (sel) act_b <= 1'b0; else act_a <= 1'b0;
                    phase <= RST;
                end
                RST: begin
                    if (sel) rst_b_n <= 1'b0; else rst_a_n <= 1'b0;
                    phase <= OFF;
                end
                OFF: begin
                    if (sel) begin pwr_b <= 1'b0; iso_b <= 1'b1; end
                    else     begin pwr_a <= 1'b0; iso_a <= 1'b1; end
                    phase <= IDLE;
                end
                WAIT: begin
                    if (count <= 4'd1) begin
                        if (sel) rst_b_n <= 1'b1; else rst_a_n <= 1'b1;
                        phase <= RESTORE;
                    end else count <= count - 4'd1;
                end
                RESTORE: phase <= REL;
                default: begin  // REL
                    if (sel) begin iso_b <= 1'b0; act_b <= 1'b1; end
                    else     begin iso_a <= 1'b0; act_a <= 1'b1; end
                    phase <= IDLE;
                end
            endcase
        end
    end
endmodule
