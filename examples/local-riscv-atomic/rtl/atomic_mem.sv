// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Two harts share four words through one request port: LOAD, STORE, LR, SC and the nine AMOs.
// A hart keeps one reservation: the address of its last LR. A write by the other hart into the
// same reservation set (2**GRAIN words) removes it; so does any SC of its own. An AMO reads in
// its first cycle and writes in its second, and no other request is taken in between.
`timescale 1ns/1ps
module atomic_mem #(parameter integer GRAIN = 0, MUTATION = 0) (
    input wire clk, rst_n, req_valid, hart,
    input wire [2:0] op,
    input wire [3:0] fn,
    input wire [1:0] address,
    input wire [31:0] write_data,
    input wire [1:0] resp_ready,
    output wire req_ready,
    output reg [1:0] resp_valid,
    output wire [63:0] resp_data,
    output wire [127:0] visible_memory
);
    localparam [2:0] LOAD = 3'd0, STORE = 3'd1, LR = 3'd2, SC = 3'd3, AMO = 3'd4;
    reg [31:0] memory [0:3];
    reg [31:0] result [0:1];
    reg [1:0] reserved;           // one flag per hart
    reg [1:0] reserved_at [0:1];  // the address of its LR
    reg amo_busy, amo_hart;
    reg [3:0] amo_fn;
    reg [1:0] amo_address;
    reg [31:0] amo_operand, amo_old;

    assign resp_data = {result[1], result[0]};
    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin : expose
        assign visible_memory[32*g +: 32] = memory[g];
    end endgenerate

    // Mutation 4: the memory is not held for the second cycle of an AMO.
    wire legal = op <= AMO && (op != AMO || fn <= 4'd8);
    assign req_ready = rst_n && legal && !resp_valid[hart] && (!amo_busy || MUTATION == 4);
    wire fire = req_valid && req_ready;

    // Mutation 2: any address is good enough for a hart that holds a reservation.
    wire sc_ok = reserved[hart] && (reserved_at[hart] == address || MUTATION == 2);
    // Mutation 5: an SC that fails still writes.
    wire sc_write = fire && op == SC && (sc_ok || MUTATION == 5);

    // Mutation 6: MIN and MAX compare as unsigned numbers.
    wire signed_less = MUTATION == 6 ? amo_old < amo_operand : $signed(amo_old) < $signed(amo_operand);
    wire unsigned_less = amo_old < amo_operand;
    reg [31:0] amo_new;
    always @* begin
        case (amo_fn)
            4'd0: amo_new = amo_operand;
            4'd1: amo_new = amo_old + amo_operand;
            4'd2: amo_new = amo_old ^ amo_operand;
            4'd3: amo_new = amo_old & amo_operand;
            4'd4: amo_new = amo_old | amo_operand;
            4'd5: amo_new = signed_less ? amo_old : amo_operand;
            4'd6: amo_new = signed_less ? amo_operand : amo_old;
            4'd7: amo_new = unsigned_less ? amo_old : amo_operand;
            default: amo_new = unsigned_less ? amo_operand : amo_old;
        endcase
    end

    // The one write of this cycle, and who it is from.
    wire store_write = fire && op == STORE;
    wire write = amo_busy || store_write || sc_write;
    wire writer = amo_busy ? amo_hart : hart;
    wire [1:0] write_address = amo_busy ? amo_address : address;
    // Mutation 1: a plain store of the other hart leaves the reservation in place.
    wire breaks = write && !(MUTATION == 1 && !amo_busy && store_write);

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            resp_valid <= 2'b00; reserved <= 2'b00; amo_busy <= 1'b0; amo_hart <= 1'b0;
            amo_fn <= 4'd0; amo_address <= 2'd0; amo_operand <= 32'd0; amo_old <= 32'd0;
            for (i = 0; i < 4; i = i + 1) memory[i] <= 32'd0;
            for (i = 0; i < 2; i = i + 1) begin result[i] <= 32'd0; reserved_at[i] <= 2'd0; end
        end else begin
            for (i = 0; i < 2; i = i + 1) begin
                if (resp_valid[i] && resp_ready[i]) resp_valid[i] <= 1'b0;
                if (breaks && writer != i[0] &&
                    (write_address >> GRAIN) == (reserved_at[i] >> GRAIN)) reserved[i] <= 1'b0;
            end
            if (fire) begin
                case (op)
                    LOAD: begin result[hart] <= memory[address]; resp_valid[hart] <= 1'b1; end
                    STORE: begin memory[address] <= write_data; result[hart] <= 32'd0; resp_valid[hart] <= 1'b1; end
                    LR: begin
                        result[hart] <= memory[address]; resp_valid[hart] <= 1'b1;
                        reserved[hart] <= 1'b1; reserved_at[hart] <= address;
                    end
                    SC: begin
                        if (sc_write) memory[address] <= write_data;
                        result[hart] <= {31'd0, !sc_ok}; resp_valid[hart] <= 1'b1;
                        // Mutation 3: a successful SC keeps the reservation.
                        if (!(MUTATION == 3 && sc_ok)) reserved[hart] <= 1'b0;
                    end
                    default: begin
                        amo_busy <= 1'b1; amo_hart <= hart; amo_fn <= fn; amo_address <= address;
                        amo_operand <= write_data; amo_old <= memory[address];
                    end
                endcase
            end
            // Last, so that with mutation 4 the AMO overwrites what was stored in between.
            if (amo_busy) begin
                memory[amo_address] <= amo_new; result[amo_hart] <= amo_old;
                resp_valid[amo_hart] <= 1'b1; amo_busy <= 1'b0;
            end
        end
    end
endmodule
