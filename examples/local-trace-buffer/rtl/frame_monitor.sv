// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// The circuit that failed in the field: frames are byte runs between flags (8'h7e); error is a
// one-clock pulse, the clock after a data byte that makes a frame longer than MAXLEN bytes.
// MUTATION=1 is the old revision: a flag right after a flag counts as a data byte, so a frame of
// exactly MAXLEN bytes after two flags in a row is reported as too long.
module frame_monitor #(parameter MAXLEN = 4, MUTATION = 0) (
    input wire clk, rst_n, valid,
    input wire [7:0] data,
    output reg error
);
    localparam [7:0] FLAG = 8'h7e;
    localparam [2:0] LIMIT = MAXLEN[2:0];
    reg [2:0] count;
    reg last_flag;
    wire is_flag = data == FLAG;
    always @(posedge clk) begin
        error <= 1'b0;
        if (!rst_n) begin
            count <= 3'd0;
            last_flag <= 1'b0;
        end else if (valid) begin
            last_flag <= is_flag;
            if (is_flag && !(MUTATION == 1 && last_flag)) count <= 3'd0;
            else begin
                count <= count == 3'd7 ? count : count + 3'd1;
                if (!is_flag && count >= LIMIT) error <= 1'b1;
            end
        end
    end
endmodule
