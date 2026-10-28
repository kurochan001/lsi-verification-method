module jtag_tap #(parameter IDCODE=32'h12345679, MUTATION=0)(
    input wire tck, tms, tdi, trst_n,
    input wire [7:0] pin_in,
    output wire tdo,
    output wire [7:0] pin_out
);
    localparam TLR=0, RTI=1, SEL_DR=2, CAP_DR=3, SHIFT_DR=4, EXIT1_DR=5, PAUSE_DR=6,
               EXIT2_DR=7, UPD_DR=8, SEL_IR=9, CAP_IR=10, SHIFT_IR=11, EXIT1_IR=12,
               PAUSE_IR=13, EXIT2_IR=14, UPD_IR=15;
    localparam IDCODE_IR=4'b0001, BYPASS=4'b1111, SAMPLE=4'b0010, EXTEST=4'b0011;

    reg [3:0] state;
    reg [3:0] ir;
    reg [3:0] ir_shift;
    reg [31:0] id_shift;
    reg [7:0] bsr, bsr_update;
    reg bypass_reg;
    reg tdo_reg;
    reg [3:0] next_state;

    assign tdo = tdo_reg;
    assign pin_out = ir == EXTEST ? bsr_update : pin_in;

    always @* begin
        case (state)
            TLR: next_state = tms ? TLR : RTI;
            RTI: next_state = tms ? SEL_DR : RTI;
            SEL_DR: next_state = tms ? SEL_IR : CAP_DR;
            CAP_DR: next_state = tms ? EXIT1_DR : SHIFT_DR;
            SHIFT_DR: next_state = tms ? EXIT1_DR : SHIFT_DR;
            EXIT1_DR: next_state = tms ? UPD_DR : PAUSE_DR;
            PAUSE_DR: next_state = tms ? EXIT2_DR : PAUSE_DR;
            EXIT2_DR: next_state = MUTATION == 4 ? UPD_DR : (tms ? UPD_DR : SHIFT_DR);
            UPD_DR: next_state = tms ? SEL_DR : RTI;
            SEL_IR: next_state = tms ? TLR : CAP_IR;
            CAP_IR: next_state = tms ? EXIT1_IR : SHIFT_IR;
            SHIFT_IR: next_state = tms ? EXIT1_IR : SHIFT_IR;
            EXIT1_IR: next_state = tms ? UPD_IR : PAUSE_IR;
            PAUSE_IR: next_state = tms ? EXIT2_IR : PAUSE_IR;
            EXIT2_IR: next_state = tms ? UPD_IR : SHIFT_IR;
            UPD_IR: next_state = tms ? SEL_DR : RTI;
            default: next_state = TLR;
        endcase
    end

    always @(posedge tck or negedge trst_n) begin
        if (!trst_n) begin
            state <= TLR; ir_shift <= 4'b0001;
            id_shift <= 0; bsr <= 0; bypass_reg <= 0;
        end else begin
            state <= next_state;
            case (state)
                CAP_DR: begin
                    case (ir)
                        IDCODE_IR: id_shift <= IDCODE ^ (MUTATION == 1 ? 32'h1 : 32'h0);
                        SAMPLE, EXTEST: bsr <= pin_in;
                        default: bypass_reg <= 0;
                    endcase
                end
                SHIFT_DR: begin
                    case (ir)
                        IDCODE_IR: id_shift <= {tdi, id_shift[31:1]};
                        SAMPLE, EXTEST: bsr <= {tdi, bsr[7:1]};
                        default: bypass_reg <= tdi;
                    endcase
                end
                CAP_IR: ir_shift <= 4'b0001;
                SHIFT_IR: ir_shift <= {tdi, ir_shift[3:1]};
                default: begin end
            endcase
        end
    end

    // Update latches are distinct from the capture/shift registers.
    always @(negedge tck or negedge trst_n) begin
        if (!trst_n) begin ir <= IDCODE_IR; bsr_update <= 0; end
        else begin
            if (state == TLR) ir <= IDCODE_IR;
            else if (state == UPD_IR) ir <= MUTATION == 2 ? (ir_shift ^ 4'b0001) : ir_shift;
            if (state == UPD_DR && (ir == SAMPLE || ir == EXTEST) && !(MUTATION == 3 && ir == EXTEST))
                bsr_update <= bsr;
        end
    end

    always @(negedge tck or negedge trst_n) begin
        if (!trst_n) tdo_reg <= 0;
        else if (state == SHIFT_DR) begin
            case (ir)
                IDCODE_IR: tdo_reg <= id_shift[0];
                SAMPLE, EXTEST: tdo_reg <= bsr[0];
                default: tdo_reg <= bypass_reg;
            endcase
        end else if (state == SHIFT_IR) tdo_reg <= ir_shift[0];
        else tdo_reg <= 0;
    end
endmodule
