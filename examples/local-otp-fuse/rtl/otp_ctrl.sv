// A controller for a one-time programmable memory (OTP, fuses).
//
// Every word has four rows of WB cells in the array: three copies of the data (rows 0, 1, 2) and
// a lock row (row 3), whose bits 0..2 are three copies of the lock bit. A cell can only go from
// 0 to 1, by a programming pulse of PROG cycles on its row; a pulse cut short changes nothing.
//
// A read gives the bit-wise majority of the three copies (resp_data), their OR (resp_any), whether
// they disagree (resp_corrected) and whether the word is locked (majority of the lock copies).
// A write is refused when the word is locked. Otherwise it programs the three copies one after
// another, reads them back, and programs the lock row only when the majority equals the value
// written; otherwise it answers with resp_err and leaves the word unlocked. Since bits can only be
// set, a write onto copies that already hold other ones fails this verification.
//
// The reset is asynchronous: it is also what a loss of power looks like. It stops a pulse at
// once. The cells keep what was programmed; the copies of a word written when the power went
// may then disagree, and the word stays unlocked until a write completes.
//
// Timing, counted in rising edges after the one that takes the request:
//   read: response at edge 4.  write to a locked word: at edge 1.
//   write: row r is programmed at edge (r+1)*PROG+1, the copies are read back at edges
//   3*PROG+2..3*PROG+4, the lock row is programmed at edge 4*PROG+4 and the response follows
//   at the same edge; when the read-back differs, the response comes at edge 3*PROG+4.
module otp_ctrl #(
    parameter MUTATION = 0,
    parameter NW = 16,          // words
    parameter WB = 8,           // bits of a word, at least 3
    parameter PROG = 3,         // cycles of a programming pulse, at least 2
    parameter AW = $clog2(NW)
) (
    input  wire          clk,
    input  wire          rst_n,          // asynchronous, active low; also a loss of power
    input  wire          req_valid,
    input  wire          req_write,
    input  wire [AW-1:0] req_addr,
    input  wire [WB-1:0] req_wdata,
    output wire          req_ready,
    output reg           resp_valid,
    output reg  [WB-1:0] resp_data,      // majority of the three copies
    output reg  [WB-1:0] resp_any,       // OR of the three copies
    output reg           resp_err,       // write refused (locked) or read-back differs
    output reg           resp_corrected, // the copies disagree
    output reg           resp_locked,
    // the cell array
    output wire [AW-1:0] cell_word,
    output wire [1:0]    cell_row,
    input  wire [WB-1:0] cell_rdata,     // the row named by cell_word and cell_row
    output wire          prog_en,
    output wire [WB-1:0] prog_mask
);
    localparam S_IDLE = 3'd0, S_LOCK = 3'd1, S_PROG = 3'd2, S_VERIFY = 3'd3, S_READ = 3'd4, S_RESP = 3'd5;
    localparam [WB-1:0] LOCK_BITS = 7;
    // Mutation 5: the pulse is one cycle short.
    localparam integer PULSE = MUTATION == 5 ? PROG - 1 : PROG;
    localparam CW = $clog2(PROG + 1);
    localparam [CW-1:0] LAST = PULSE[CW-1:0] - 1'b1;

    reg [2:0]    state;
    reg [1:0]    row;
    reg [CW-1:0] cnt;
    reg          prog_q;
    reg          write_q;
    reg [AW-1:0] addr_q;
    reg [WB-1:0] wdata_q, c0, c1;

    function [WB-1:0] majority(input [WB-1:0] a, input [WB-1:0] b, input [WB-1:0] c);
        majority = (a & b) | (b & c) | (a & c);
    endfunction

    assign req_ready = state == S_IDLE;
    assign cell_word = addr_q;
    assign cell_row = row;
    // Mutation 6: during a reset the pulse driver keeps the value of the last clock edge, as if
    // it were reset only by the clock; a pulse that was running goes on while the power fails.
    reg prog_late;
    always @(posedge clk) prog_late <= prog_q;
    assign prog_en = prog_q || (MUTATION == 6 && !rst_n && prog_late);
    assign prog_mask = row == 2'd3 ? LOCK_BITS : wdata_q;

    wire lock_now = (cell_rdata[0] & cell_rdata[1]) | (cell_rdata[1] & cell_rdata[2]) | (cell_rdata[0] & cell_rdata[2]);
    // The three copies, the last one straight from the array.
    wire [WB-1:0] c2 = cell_rdata;
    // Mutation 2: the data is taken from the first copy alone.
    wire [WB-1:0] maj = MUTATION == 2 ? c0 : majority(c0, c1, c2);
    // Mutation 3: only the first two copies are compared.
    wire disagree = MUTATION == 3 ? c0 != c1 : (c0 != c1 || c1 != c2);
    // Mutation 4: the lock row is programmed first, before the data.
    wire [1:0] first_row = MUTATION == 4 ? 2'd3 : 2'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; row <= 2'd0; cnt <= {CW{1'b0}};
            prog_q <= 1'b0;
            write_q <= 1'b0; addr_q <= {AW{1'b0}}; wdata_q <= {WB{1'b0}};
            c0 <= {WB{1'b0}}; c1 <= {WB{1'b0}};
            resp_valid <= 1'b0; resp_data <= {WB{1'b0}}; resp_any <= {WB{1'b0}};
            resp_err <= 1'b0; resp_corrected <= 1'b0; resp_locked <= 1'b0;
        end else begin
            resp_valid <= 1'b0;
            case (state)
                S_IDLE: if (req_valid) begin
                    write_q <= req_write; addr_q <= req_addr; wdata_q <= req_wdata;
                    row <= 2'd3;
                    state <= S_LOCK;
                end
                S_LOCK: begin
                    // Mutation 1: a write does not look at the lock.
                    if (req_write_locked(write_q, lock_now)) begin
                        resp_valid <= 1'b1; resp_data <= {WB{1'b0}}; resp_any <= {WB{1'b0}};
                        resp_err <= 1'b1; resp_corrected <= 1'b0; resp_locked <= 1'b1;
                        state <= S_RESP;
                    end else if (write_q) begin
                        row <= first_row; cnt <= {CW{1'b0}}; prog_q <= 1'b1;
                        state <= S_PROG;
                    end else begin
                        resp_locked <= lock_now;
                        row <= 2'd0;
                        state <= S_READ;
                    end
                end
                S_PROG: begin
                    if (cnt == LAST) begin
                        cnt <= {CW{1'b0}};
                        if (MUTATION == 4 ? row == 2'd2 : row == 2'd3) begin
                            prog_q <= 1'b0;
                            if (MUTATION == 4) begin row <= 2'd0; state <= S_VERIFY; end
                            else begin
                                resp_valid <= 1'b1; resp_err <= 1'b0; resp_locked <= 1'b1;
                                state <= S_RESP;
                            end
                        end else if (row == 2'd2) begin
                            prog_q <= 1'b0; row <= 2'd0;
                            state <= S_VERIFY;
                        end else begin
                            row <= row == 2'd3 ? 2'd0 : row + 1'b1;
                        end
                    end else begin
                        cnt <= cnt + 1'b1;
                    end
                end
                S_VERIFY, S_READ: begin
                    if (row == 2'd0) begin c0 <= cell_rdata; row <= 2'd1; end
                    else if (row == 2'd1) begin c1 <= cell_rdata; row <= 2'd2; end
                    else begin
                        resp_data <= maj; resp_any <= c0 | c1 | c2; resp_corrected <= disagree;
                        if (state == S_READ) begin
                            resp_valid <= 1'b1; resp_err <= 1'b0;
                            state <= S_RESP;
                        end else if (maj == wdata_q && MUTATION != 4) begin
                            row <= 2'd3; cnt <= {CW{1'b0}}; prog_q <= 1'b1;
                            state <= S_PROG;
                        end else begin
                            resp_valid <= 1'b1; resp_err <= maj != wdata_q;
                            resp_locked <= MUTATION == 4;
                            state <= S_RESP;
                        end
                    end
                end
                default: state <= S_IDLE;   // S_RESP: the response is shown for this one cycle
            endcase
        end
    end

    function req_write_locked(input write, input locked);
        req_write_locked = write && locked && MUTATION != 1;
    endfunction
endmodule
