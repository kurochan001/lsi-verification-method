// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module lbist_logic (
    input wire [3:0] stimulus,
    input wire fault_enable, fault_value,
    input wire [1:0] fault_site,
    output wire [3:0] response
);
    wire [3:0] good;
    assign good = {stimulus[0] & ~stimulus[3], stimulus[2] | stimulus[3],
                   stimulus[1] & stimulus[2], stimulus[0] ^ stimulus[1]};
    // Verification hooks model eight single output stuck-at faults.
    genvar bit_index;
    generate for (bit_index=0; bit_index<4; bit_index=bit_index+1) begin : faults
        assign response[bit_index] = fault_enable && int'(fault_site)==bit_index
                                  ? fault_value : good[bit_index];
    end endgenerate
endmodule
