// Start-up sequence after reset: wait, load the straps, calibrate with a time-out, then ready.
// MUTATION 4: reset clears the power-on flag. 5: waits one clock less. 6: remembers an early cal_done.
// 7: the time-out is one clock longer. 8: keeps following the straps during calibration. 9: cfg has no reset.
module por_init_ctrl #(parameter WAIT = 4, CAL_TIMEOUT = 8, MUTATION = 0)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire [3:0] strap,
    input  wire       cal_done,
    input  wire       flag_clr,
    output wire       cfg_load,
    output wire       cal_start,
    output wire       ready,
    output wire       init_fail,
    output reg  [3:0] cfg,
    output reg        por_flag
);
    localparam [2:0] S_WAIT = 3'd0, S_LOAD = 3'd1, S_CAL = 3'd2, S_READY = 3'd3, S_FAIL = 3'd4;
    localparam [7:0] WAIT_LAST = (MUTATION == 5) ? WAIT[7:0] - 8'd2 : WAIT[7:0] - 8'd1;
    localparam [7:0] CAL_LAST  = (MUTATION == 7) ? CAL_TIMEOUT[7:0] : CAL_TIMEOUT[7:0] - 8'd1;
    reg [2:0] state;
    reg [7:0] count;
    reg       early;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            state <= S_WAIT;
            count <= 8'd0;
            early <= 1'b0;
            por_flag <= (MUTATION != 4);
        end else begin
            if (flag_clr) por_flag <= 1'b0;
            case (state)
                S_WAIT: begin
                    early <= (MUTATION == 6) && (early || cal_done);
                    if (count == WAIT_LAST) begin state <= S_LOAD; count <= 8'd0; end
                    else count <= count + 8'd1;
                end
                S_LOAD: begin
                    early <= (MUTATION == 6) && (early || cal_done);
                    state <= S_CAL;
                    count <= 8'd0;
                end
                S_CAL:
                    if (cal_done || early) state <= S_READY;
                    else if (count == CAL_LAST) state <= S_FAIL;
                    else count <= count + 8'd1;
                default: ;
            endcase
        end

    wire take = (state == S_LOAD) || (MUTATION == 8 && state == S_CAL);
    generate
        if (MUTATION == 9) begin : g_no_reset
            always @(posedge clk) if (take) cfg <= strap;
        end else begin : g_reset
            always @(posedge clk or negedge rst_n)
                if (!rst_n) cfg <= 4'd0;
                else if (take) cfg <= strap;
        end
    endgenerate

    assign cfg_load  = state == S_LOAD;
    assign cal_start = state == S_CAL;
    assign ready     = state == S_READY;
    assign init_fail = state == S_FAIL;
endmodule
