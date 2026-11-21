// 8b/10b encoder, combinational part. The sub-block codes are written out as tables.
// data is HGFEDCBA, code is abcdeifghj with code[9] = a, the first bit sent.
// rd is the running disparity before this character: 0 minus, 1 plus.
// MUTATION: 1 D.7 never alternates, 2 no alternate .7 after D.20, 3 the running disparity
// ignores the 4-bit sub-block, 4 K.28.1/2/5/6 are not complemented for minus.
module enc_8b10b_comb #(parameter MUTATION = 0) (
    input  wire [7:0] data,
    input  wire       k,
    input  wire       rd,
    output wire [9:0] code,
    output wire       rd_next,
    output wire       k_err
);
    wire [4:0] x = data[4:0];
    wire [2:0] y = data[7:5];
    wire k28 = k && x == 5'd28;
    wire k_other = k && y == 3'd7 && (x == 5'd23 || x == 5'd27 || x == 5'd29 || x == 5'd30);
    assign k_err = k && !k28 && !k_other;

    // {plus form is the complement, the 6-bit sub-block for running disparity minus}.
    function [6:0] six_table(input [4:0] value);
        case (value)
            5'd0:  six_table = {1'b1, 6'b100111};
            5'd1:  six_table = {1'b1, 6'b011101};
            5'd2:  six_table = {1'b1, 6'b101101};
            5'd3:  six_table = {1'b0, 6'b110001};
            5'd4:  six_table = {1'b1, 6'b110101};
            5'd5:  six_table = {1'b0, 6'b101001};
            5'd6:  six_table = {1'b0, 6'b011001};
            5'd7:  six_table = {MUTATION != 1, 6'b111000};
            5'd8:  six_table = {1'b1, 6'b111001};
            5'd9:  six_table = {1'b0, 6'b100101};
            5'd10: six_table = {1'b0, 6'b010101};
            5'd11: six_table = {1'b0, 6'b110100};
            5'd12: six_table = {1'b0, 6'b001101};
            5'd13: six_table = {1'b0, 6'b101100};
            5'd14: six_table = {1'b0, 6'b011100};
            5'd15: six_table = {1'b1, 6'b010111};
            5'd16: six_table = {1'b1, 6'b011011};
            5'd17: six_table = {1'b0, 6'b100011};
            5'd18: six_table = {1'b0, 6'b010011};
            5'd19: six_table = {1'b0, 6'b110010};
            5'd20: six_table = {1'b0, 6'b001011};
            5'd21: six_table = {1'b0, 6'b101010};
            5'd22: six_table = {1'b0, 6'b011010};
            5'd23: six_table = {1'b1, 6'b111010};
            5'd24: six_table = {1'b1, 6'b110011};
            5'd25: six_table = {1'b0, 6'b100110};
            5'd26: six_table = {1'b0, 6'b010110};
            5'd27: six_table = {1'b1, 6'b110110};
            5'd28: six_table = {1'b0, 6'b001110};
            5'd29: six_table = {1'b1, 6'b101110};
            5'd30: six_table = {1'b1, 6'b011110};
            default: six_table = {1'b1, 6'b101011};
        endcase
    endfunction
    wire [6:0] six_entry = k28 ? {1'b1, 6'b001111} : six_table(x);
    wire [5:0] six_minus = six_entry[5:0];
    wire six_flips = six_entry[6];
    wire [5:0] six = rd && six_flips ? ~six_minus : six_minus;
    wire [2:0] six_ones = {2'b00, six[5]} + {2'b00, six[4]} + {2'b00, six[3]} +
                          {2'b00, six[2]} + {2'b00, six[1]} + {2'b00, six[0]};
    wire rd_mid = six_ones == 3'd3 ? rd : six_ones > 3'd3;

    // The 4-bit sub-block for the running disparity after the 6-bit sub-block.
    wire alternate7 = k || (!rd_mid && (x == 5'd17 || x == 5'd18 || (x == 5'd20 && MUTATION != 2))) ||
                      (rd_mid && (x == 5'd11 || x == 5'd13 || x == 5'd14));
    // {the plus form is the complement, the 4-bit sub-block for running disparity minus}.
    function [4:0] four_table(input [2:0] value, input alternate);
        case (value)
            3'd0: four_table = {1'b1, 4'b1011};
            3'd1: four_table = {1'b0, 4'b1001};
            3'd2: four_table = {1'b0, 4'b0101};
            3'd3: four_table = {1'b1, 4'b1100};
            3'd4: four_table = {1'b1, 4'b1101};
            3'd5: four_table = {1'b0, 4'b1010};
            3'd6: four_table = {1'b0, 4'b0110};
            default: four_table = {1'b1, alternate ? 4'b0111 : 4'b1110};
        endcase
    endfunction
    wire [4:0] four_entry = four_table(y, alternate7);
    wire [3:0] four_minus = four_entry[3:0];
    wire four_flips = four_entry[4];
    // A control character sends the complement of the balanced data codes when the disparity is minus.
    wire k_complement = k && !four_flips && !rd_mid && MUTATION != 4;
    wire [3:0] four = (rd_mid && four_flips) || k_complement ? ~four_minus : four_minus;
    wire [2:0] four_ones = {2'b00, four[3]} + {2'b00, four[2]} + {2'b00, four[1]} + {2'b00, four[0]};
    wire rd_after = four_ones == 3'd2 ? rd_mid : four_ones > 3'd2;

    assign code = k_err ? 10'd0 : {six, four};
    assign rd_next = k_err ? rd : MUTATION == 3 ? rd_mid : rd_after;
endmodule
