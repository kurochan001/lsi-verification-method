// Two-bit IR and a 32-bit APB scan register. The teaching bridge and its
// peripheral share TCK. Each TAP action uses the state before the rising edge.
module jtag_apb #(parameter MUTATION=0)(
    input wire tck, trst_n, tms, tdi, pready, pslverr,
    input wire [7:0] prdata,
    output reg tdo, pwrite, err,
    output wire psel, penable,
    output reg [7:0] paddr, pwdata,
    output reg [3:0] state,
    output reg [1:0] ir
);
    localparam TLR=0, IDLE=1, SEL_DR=2, CAP_DR=3, SHIFT_DR=4, EXIT1_DR=5,
               PAUSE_DR=6, EXIT2_DR=7, UPD_DR=8, SEL_IR=9, CAP_IR=10,
               SHIFT_IR=11, EXIT1_IR=12, PAUSE_IR=13, EXIT2_IR=14, UPD_IR=15;
    localparam IDCODE=1, BYPASS=2, APB_ACC=3;
    reg [3:0] next_state;
    always @* begin
        case (state)
            TLR:      next_state = tms ? TLR : IDLE;
            IDLE:     next_state = tms ? SEL_DR : IDLE;
            SEL_DR:   next_state = tms ? SEL_IR : CAP_DR;
            CAP_DR:   next_state = tms ? EXIT1_DR : SHIFT_DR;
            SHIFT_DR: next_state = tms ? EXIT1_DR : SHIFT_DR;
            EXIT1_DR: next_state = tms ? UPD_DR : PAUSE_DR;
            PAUSE_DR: next_state = tms ? EXIT2_DR : PAUSE_DR;
            EXIT2_DR: next_state = tms ? UPD_DR : SHIFT_DR;
            UPD_DR:   next_state = tms ? SEL_DR : IDLE;
            SEL_IR:   next_state = tms ? TLR : CAP_IR;
            CAP_IR:   next_state = tms ? EXIT1_IR : SHIFT_IR;
            SHIFT_IR: next_state = tms ? EXIT1_IR : SHIFT_IR;
            EXIT1_IR: next_state = tms ? UPD_IR : PAUSE_IR;
            PAUSE_IR: next_state = tms ? EXIT2_IR : PAUSE_IR;
            EXIT2_IR: next_state = tms ? UPD_IR : SHIFT_IR;
            UPD_IR:   next_state = tms ? SEL_DR : IDLE;
            default:  next_state = TLR;
        endcase
    end
    reg [1:0] ir_shift;
    reg [31:0] dr, last_cmd;
    reg [7:0] last_read;
    reg [1:0] phase;
    assign psel = phase != 0;
    assign penable = phase >= 2;
    always @(posedge tck or negedge trst_n) begin
        if (!trst_n) begin
            state <= TLR; ir <= IDCODE; ir_shift <= 0; dr <= 0; tdo <= 0;
            phase <= 0; paddr <= 0; pwdata <= 0; pwrite <= 0;
            last_cmd <= 0; last_read <= 0; err <= 0;
        end else begin
            state <= next_state;
            tdo <= 0;
            if (next_state == TLR) ir <= IDCODE;
            if (MUTATION == 3) err <= 0;
            if (phase == 1) phase <= 2;
            else if (phase == 2 && pready) begin
                phase <= MUTATION == 2 ? 3 : 0;
                if (pslverr) err <= 1;
                else if (!pwrite) begin
                    last_read <= prdata;
                    if (prdata[7]) err <= 0;
                end
            end else if (phase == 3) phase <= 0;
            case (state)
                TLR: ir <= IDCODE;
                CAP_IR: ir_shift <= 2'b01;
                SHIFT_IR: begin tdo <= ir_shift[0]; ir_shift <= {tdi,ir_shift[1]}; end
                UPD_IR: ir <= ir_shift;
                CAP_DR: case (ir)
                    IDCODE: dr <= 32'hB7071149;
                    APB_ACC: dr <= MUTATION == 1 ? last_cmd : {8'd0,last_read,15'd0,err};
                    default: dr <= 0;
                endcase
                SHIFT_DR: begin
                    tdo <= dr[0];
                    if (ir == BYPASS || ir == 0) dr <= {31'd0,tdi};
                    else dr <= {tdi,dr[31:1]};
                end
                UPD_DR: if (ir == APB_ACC && dr[1] && phase == 0) begin
                    paddr <= dr[31:24]; pwdata <= dr[23:16];
                    pwrite <= MUTATION == 4 ? 1'b1 : dr[2];
                    last_cmd <= dr;
                    phase <= 1;
                end
                default: begin end
            endcase
        end
    end
endmodule
