// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module lbist #(
    parameter integer PATTERNS=16, MUTATION=0
) (
    input wire clk, rst_n, test_mode, start,
    input wire [7:0] seed, expected_signature,
    input wire [3:0] normal_in,
    input wire fault_enable, fault_value,
    input wire [1:0] fault_site,
    input wire [3:0] response_xor,
    output wire [3:0] normal_out, raw_response,
    output reg busy, done, failed, seed_error,
    output reg [7:0] signature, prpg, pattern_count
);
    reg [7:0] expected_latched;
    wire [3:0] stimulus = test_mode && busy ? prpg[3:0] : normal_in;
    wire [3:0] logic_response;
    wire [7:0] next_prpg = {prpg[6:0], prpg[7]^prpg[5]^prpg[4]^prpg[3]};
    wire [7:0] next_signature = {signature[6:0],1'b0}
                             ^ (signature[7] ? 8'h1d : 8'h00)
                             ^ {4'b0000,raw_response}
                             ^ (MUTATION==2 ? 8'h01 : 8'h00);

    lbist_logic logic_under_test (
        .stimulus(stimulus), .fault_enable(fault_enable),
        .fault_site(fault_site), .fault_value(fault_value), .response(logic_response)
    );
    // All fault and XOR inputs are verification hooks, tied off in normal use.
    assign raw_response = logic_response ^ response_xor;
    assign normal_out = test_mode ? 4'b0000 : logic_response;

    always @(posedge clk) begin
        if (!rst_n || !test_mode) begin
            busy <= 0; done <= 0; failed <= 0; seed_error <= 0;
            signature <= 0; prpg <= 0; pattern_count <= 0; expected_latched <= 0;
        end else if (busy) begin
            signature <= next_signature;
            prpg <= MUTATION==1 ? prpg : next_prpg;
            pattern_count <= pattern_count + 8'd1;
            if (int'(pattern_count)==PATTERNS-1-(MUTATION==3 ? 1 : 0)) begin
                busy <= 0;
                done <= 1;
                failed <= MUTATION==4 ? 1'b0 : next_signature!=expected_latched;
            end
        end else if (start) begin
            signature <= 0; pattern_count <= 0; done <= 0; failed <= 0;
            if (seed==0) begin
                prpg <= 0; seed_error <= 1;
            end else begin
                prpg <= seed; expected_latched <= expected_signature;
                seed_error <= 0; busy <= 1;
            end
        end
    end
endmodule
