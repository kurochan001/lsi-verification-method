// 8b/10b decoder, combinational part. It works on the two sub-blocks and on the rules that tie
// them together, not on a table of ten-bit codes.
//   code_err  the code is not produced by the encoder for either running disparity
//   disp_err  the code exists, but only for the other running disparity
// rd_next follows the sign of an unbalanced code, whether or not the code was accepted.
// MUTATION: 5 a disparity error is not reported, 6 the alternate .7 is accepted after any data
// value, 7 the running disparity does not move on a rejected code.
module dec_8b10b_comb #(parameter MUTATION = 0) (
    input  wire [9:0] code,
    input  wire       rd,
    output wire [7:0] data,
    output wire       k,
    output wire       code_err,
    output wire       disp_err,
    output wire       rd_next
);
    wire [5:0] six = code[9:4];
    wire [3:0] four = code[3:0];

    // 6-bit sub-block: {accepted, K.28, value}.
    function [6:0] six_decode(input [5:0] c);
        case (c)
            6'b100111, 6'b011000: six_decode = {1'b1, 1'b0, 5'd0};
            6'b011101, 6'b100010: six_decode = {1'b1, 1'b0, 5'd1};
            6'b101101, 6'b010010: six_decode = {1'b1, 1'b0, 5'd2};
            6'b110001: six_decode = {1'b1, 1'b0, 5'd3};
            6'b110101, 6'b001010: six_decode = {1'b1, 1'b0, 5'd4};
            6'b101001: six_decode = {1'b1, 1'b0, 5'd5};
            6'b011001: six_decode = {1'b1, 1'b0, 5'd6};
            6'b111000, 6'b000111: six_decode = {1'b1, 1'b0, 5'd7};
            6'b111001, 6'b000110: six_decode = {1'b1, 1'b0, 5'd8};
            6'b100101: six_decode = {1'b1, 1'b0, 5'd9};
            6'b010101: six_decode = {1'b1, 1'b0, 5'd10};
            6'b110100: six_decode = {1'b1, 1'b0, 5'd11};
            6'b001101: six_decode = {1'b1, 1'b0, 5'd12};
            6'b101100: six_decode = {1'b1, 1'b0, 5'd13};
            6'b011100: six_decode = {1'b1, 1'b0, 5'd14};
            6'b010111, 6'b101000: six_decode = {1'b1, 1'b0, 5'd15};
            6'b011011, 6'b100100: six_decode = {1'b1, 1'b0, 5'd16};
            6'b100011: six_decode = {1'b1, 1'b0, 5'd17};
            6'b010011: six_decode = {1'b1, 1'b0, 5'd18};
            6'b110010: six_decode = {1'b1, 1'b0, 5'd19};
            6'b001011: six_decode = {1'b1, 1'b0, 5'd20};
            6'b101010: six_decode = {1'b1, 1'b0, 5'd21};
            6'b011010: six_decode = {1'b1, 1'b0, 5'd22};
            6'b111010, 6'b000101: six_decode = {1'b1, 1'b0, 5'd23};
            6'b110011, 6'b001100: six_decode = {1'b1, 1'b0, 5'd24};
            6'b100110: six_decode = {1'b1, 1'b0, 5'd25};
            6'b010110: six_decode = {1'b1, 1'b0, 5'd26};
            6'b110110, 6'b001001: six_decode = {1'b1, 1'b0, 5'd27};
            6'b001110: six_decode = {1'b1, 1'b0, 5'd28};
            6'b101110, 6'b010001: six_decode = {1'b1, 1'b0, 5'd29};
            6'b011110, 6'b100001: six_decode = {1'b1, 1'b0, 5'd30};
            6'b101011, 6'b010100: six_decode = {1'b1, 1'b0, 5'd31};
            6'b001111, 6'b110000: six_decode = {1'b1, 1'b1, 5'd28};
            default: six_decode = 7'd0;
        endcase
    endfunction
    wire [6:0] six_entry = six_decode(six);
    wire [4:0] x = six_entry[4:0];
    wire k28 = six_entry[5];
    wire six_ok = six_entry[6];
    wire [2:0] six_ones = {2'b00, six[5]} + {2'b00, six[4]} + {2'b00, six[3]} +
                          {2'b00, six[2]} + {2'b00, six[1]} + {2'b00, six[0]};
    // An unbalanced sub-block, and the two forms of D.7, fix the disparity before and after it.
    wire six_needs_minus = six_ones > 3'd3 || six == 6'b111000;
    wire six_needs_plus = six_ones < 3'd3 || six == 6'b000111;
    wire six_fixed = six_needs_minus || six_needs_plus;
    wire mid_fixed = six_ones > 3'd3 || six == 6'b000111;   // the disparity after a fixing sub-block

    // 4-bit sub-block for a given disparity before it: {accepted, control by its .7, value}.
    function [4:0] four_decode(input [3:0] f, input mid, input [4:0] value, input is_k28);
        reg ok, control;
        reg [2:0] v;
        reg a7_data, a7_control;
        begin
            ok = 1'b1;
            control = 1'b0;
            v = 3'd0;
            a7_data = mid ? (value == 5'd11 || value == 5'd13 || value == 5'd14)
                          : (value == 5'd17 || value == 5'd18 || value == 5'd20);
            a7_control = value == 5'd23 || value == 5'd27 || value == 5'd29 || value == 5'd30;
            if (is_k28) begin
                case ({mid, f})
                    5'b0_1011, 5'b1_0100: v = 3'd0;
                    5'b0_0110, 5'b1_1001: v = 3'd1;
                    5'b0_1010, 5'b1_0101: v = 3'd2;
                    5'b0_1100, 5'b1_0011: v = 3'd3;
                    5'b0_1101, 5'b1_0010: v = 3'd4;
                    5'b0_0101, 5'b1_1010: v = 3'd5;
                    5'b0_1001, 5'b1_0110: v = 3'd6;
                    5'b0_0111, 5'b1_1000: v = 3'd7;
                    default: ok = 1'b0;
                endcase
            end else begin
                case ({mid, f})
                    5'b0_1011, 5'b1_0100: v = 3'd0;
                    5'b0_1001, 5'b1_1001: v = 3'd1;
                    5'b0_0101, 5'b1_0101: v = 3'd2;
                    5'b0_1100, 5'b1_0011: v = 3'd3;
                    5'b0_1101, 5'b1_0010: v = 3'd4;
                    5'b0_1010, 5'b1_1010: v = 3'd5;
                    5'b0_0110, 5'b1_0110: v = 3'd6;
                    5'b0_1110, 5'b1_0001: begin v = 3'd7; ok = !a7_data; end
                    5'b0_0111, 5'b1_1000: begin
                        v = 3'd7;
                        control = a7_control;
                        ok = a7_data || a7_control || MUTATION == 6;
                    end
                    default: ok = 1'b0;
                endcase
            end
            four_decode = {ok, control, v};
        end
    endfunction
    wire [4:0] with_minus = four_decode(four, 1'b0, x, k28);
    wire [4:0] with_plus = four_decode(four, 1'b1, x, k28);
    wire [4:0] fixed = mid_fixed ? with_plus : with_minus;
    wire [4:0] current = rd ? with_plus : with_minus;
    wire [4:0] other = rd ? with_minus : with_plus;

    // Accepted for the current disparity, or only for the other one.
    wire fits_now = six_fixed ? (six_needs_plus == rd) && fixed[4] : current[4];
    wire fits_other = six_fixed ? (six_needs_plus != rd) && fixed[4] : other[4];
    wire [3:0] chosen = six_fixed ? fixed[3:0] : fits_now ? current[3:0] : other[3:0];
    wire accepted = six_ok && (fits_now || fits_other);

    assign code_err = !accepted;
    assign disp_err = accepted && !fits_now && MUTATION != 5;
    assign data = accepted ? {chosen[2:0], x} : 8'd0;
    assign k = accepted && (k28 || chosen[3]);

    wire [3:0] ones = {1'b0, six_ones} + {3'b000, four[3]} + {3'b000, four[2]} + {3'b000, four[1]} + {3'b000, four[0]};
    assign rd_next = (MUTATION == 7 && code_err) || ones == 4'd5 ? rd : ones > 4'd5;
endmodule
