// Memory test, repair analysis and remapping for a bit-addressed array with spare rows and columns.
//
// Blank fuses: March C- over the whole physical array, spares included, collects a fault bitmap.
// The analysis then looks for rows and columns that cover every fault of the main array, using
// fault-free spares only, and programs the fuses once. After the next reset the fuses are loaded
// and the same March runs over the logical array through the remapping.
//
// Fuse layout: bit 0 is the lock. Then SR row entries {address, valid} and SC column entries.
module mem_repair #(
    parameter MUTATION = 0,
    parameter ROWS = 4,
    parameter COLS = 4,
    parameter SR = 1,
    parameter SC = 1,
    localparam PR = ROWS + SR,
    localparam PC = COLS + SC,
    localparam RB = $clog2(ROWS),
    localparam CB = $clog2(COLS),
    localparam PRW = $clog2(PR),
    localparam PCW = $clog2(PC),
    localparam FW = 1 + SR * (RB + 1) + SC * (CB + 1)
) (
    input  wire           clk,
    input  wire           rst_n,
    input  wire           start,
    output reg            ready,          // fuses loaded after reset
    output reg            busy,
    output reg            done,
    output reg  [1:0]     status,         // 0 pass, 1 repaired (reset needed), 2 unrepairable, 3 failed after repair
    output wire           repair_active,  // the loaded fuses carry a repair
    output wire           req_valid,
    input  wire           req_ready,
    output wire           req_write,
    output wire [PRW-1:0] req_row,        // physical row
    output wire [PCW-1:0] req_col,        // physical column
    output wire           req_data,
    input  wire           read_data,
    input  wire [FW-1:0]  fuse_q,
    output reg            fuse_prog,
    output reg  [FW-1:0]  fuse_d
);
    localparam [2:0] S_LOAD = 3'd0, S_IDLE = 3'd1, S_TEST = 3'd2, S_CHECK = 3'd3,
                     S_ENUM = 3'd4, S_FIN = 3'd5;
    localparam [1:0] PASS = 2'd0, REPAIRED = 2'd1, UNREPAIRABLE = 2'd2, FAILED = 2'd3;
    localparam ROW_BASE = 1;
    localparam COL_BASE = 1 + SR * (RB + 1);

    reg [2:0]         state;
    reg [FW-1:0]      map;       // fuses as loaded after reset
    reg               spent;     // fuses programmed in this power cycle: a reset must follow
    reg [2:0]         phase;     // March element: w0, up(r0,w1), up(r1,w0), down(r0,w1), down(r1,w0), r0
    reg               second;    // the write of a read-write element
    reg [PRW-1:0]     row;
    reg [PCW-1:0]     col;
    reg [PR*PC-1:0]   bitmap;    // faults by physical cell, from the test with blank fuses
    reg               test_fail;
    reg [ROWS-1:0]    mask;      // rows proposed for row repair

    wire raw = !map[0];
    assign repair_active = map[0];

    // ---- March C- ----
    wire [PRW-1:0] last_row = raw ? PRW'(PR - 1) : PRW'(ROWS - 1);
    wire [PCW-1:0] last_col = raw ? PCW'(PC - 1) : PCW'(COLS - 1);
    wire down = phase == 3'd3 || phase == 3'd4;
    wire element_last = down ? (row == {PRW{1'b0}} && col == {PCW{1'b0}})
                             : (row == last_row && col == last_col);
    wire expected = phase == 3'd2 || phase == 3'd4;
    wire element_done = phase == 3'd0 || phase == 3'd5 || second;
    wire next_down = phase == 3'd2 || phase == 3'd3;
    localparam BW = $clog2(PR * PC);
    wire [BW-1:0] cell_index = BW'(row) * BW'(PC) + BW'(col);
    assign req_valid = state == S_TEST;
    assign req_write = phase == 3'd0 || (phase != 3'd5 && second);
    assign req_data = phase == 3'd1 || phase == 3'd3;

    // ---- remapping of a logical cell to its physical cell ----
    reg [PRW-1:0] physical_row;
    reg [PCW-1:0] physical_col;
    integer i;
    always @* begin
        physical_row = row;
        physical_col = col;
        for (i = 0; i < SR; i = i + 1)
            if (!raw && map[ROW_BASE + i * (RB + 1)] && map[ROW_BASE + 1 + i * (RB + 1) +: RB] == row[RB-1:0])
                physical_row = PRW'(ROWS + i);
        for (i = 0; i < SC; i = i + 1)
            if (!raw && map[COL_BASE + i * (CB + 1)] && map[COL_BASE + 1 + i * (CB + 1) +: CB] == col[CB-1:0] &&
                    !(MUTATION == 3 && req_write))
                physical_col = PCW'(COLS + i);
    end
    assign req_row = physical_row;
    assign req_col = physical_col;

    // ---- repair analysis, combinational on the bitmap and the proposed rows ----
    reg [SR-1:0]        row_spare_bad;
    reg [SC-1:0]        col_spare_bad;
    reg [ROWS-1:0]      must;        // rows with more faults than fault-free spare columns
    reg [COLS-1:0]      need;        // columns with a fault outside the proposed rows
    reg [ROWS+COLS-1:0] row_list, col_list;
    reg [FW-1:0]        image;
    reg                 any_main, fits, found;
    integer a, b, count, rows_free, cols_free, must_count, mask_count, need_count;
    always @* begin
        found = 1'b0;
        row_spare_bad = {SR{1'b0}};
        col_spare_bad = {SC{1'b0}};
        if (MUTATION != 6) begin
            for (a = 0; a < SR; a = a + 1)
                for (b = 0; b < PC; b = b + 1)
                    if (bitmap[(ROWS + a) * PC + b]) row_spare_bad[a] = 1'b1;
            for (a = 0; a < SC; a = a + 1)
                for (b = 0; b < PR; b = b + 1)
                    if (bitmap[b * PC + COLS + a]) col_spare_bad[a] = 1'b1;
        end
        rows_free = 0;
        cols_free = 0;
        for (a = 0; a < SR; a = a + 1) if (!row_spare_bad[a]) rows_free = rows_free + 1;
        for (a = 0; a < SC; a = a + 1) if (!col_spare_bad[a]) cols_free = cols_free + 1;

        // Must-repair: a row with more faults than there are spare columns needs a spare row.
        must = {ROWS{1'b0}};
        must_count = 0;
        any_main = 1'b0;
        for (a = 0; a < ROWS; a = a + 1) begin
            count = 0;
            for (b = 0; b < COLS; b = b + 1)
                if (bitmap[a * PC + b]) begin
                    count = count + 1;
                    any_main = 1'b1;
                end
            if (MUTATION == 1 ? (count != 0 && count >= cols_free) : (count > cols_free)) begin
                must[a] = 1'b1;
                must_count = must_count + 1;
            end
        end

        // The proposed rows take spare rows; every other fault needs its column.
        need = {COLS{1'b0}};
        mask_count = 0;
        for (a = 0; a < ROWS; a = a + 1) begin
            if (mask[a]) mask_count = mask_count + 1;
            else
                for (b = 0; b < COLS; b = b + 1)
                    if (bitmap[a * PC + b]) need[b] = 1'b1;
        end
        need_count = 0;
        for (b = 0; b < COLS; b = b + 1) if (need[b]) need_count = need_count + 1;
        fits = (mask & must) == must && mask_count <= rows_free && need_count <= cols_free;

        // Fuse image: each fault-free spare, in order, takes the lowest row or column still waiting.
        row_list = {{COLS{1'b0}}, mask};
        col_list = {{ROWS{1'b0}}, need};
        if (MUTATION == 4) begin
            row_list = {{ROWS{1'b0}}, need};
            col_list = {{COLS{1'b0}}, mask};
        end
        image = {FW{1'b0}};
        image[0] = 1'b1;
        for (a = 0; a < SR; a = a + 1)
            if (!row_spare_bad[a]) begin
                found = 1'b0;
                for (b = 0; b < ROWS; b = b + 1)
                    if (!found && row_list[b]) begin
                        found = 1'b1;
                        row_list[b] = 1'b0;
                        image[ROW_BASE + a * (RB + 1)] = 1'b1;
                        image[ROW_BASE + 1 + a * (RB + 1) +: RB] = b[RB-1:0];
                    end
            end
        for (a = 0; a < SC; a = a + 1)
            if (!col_spare_bad[a]) begin
                found = 1'b0;
                for (b = 0; b < COLS; b = b + 1)
                    if (!found && col_list[b]) begin
                        found = 1'b1;
                        col_list[b] = 1'b0;
                        image[COL_BASE + a * (CB + 1)] = 1'b1;
                        image[COL_BASE + 1 + a * (CB + 1) +: CB] = b[CB-1:0];
                    end
            end
    end

    wire [1:0] unrepairable_status = MUTATION == 2 ? REPAIRED : UNREPAIRABLE;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_LOAD;
            ready <= 1'b0;
            busy <= 1'b0;
            done <= 1'b0;
            status <= PASS;
            map <= {FW{1'b0}};
            spent <= 1'b0;
            fuse_prog <= 1'b0;
            fuse_d <= {FW{1'b0}};
            phase <= 3'd0;
            second <= 1'b0;
            row <= {PRW{1'b0}};
            col <= {PCW{1'b0}};
            bitmap <= {PR*PC{1'b0}};
            test_fail <= 1'b0;
            mask <= {ROWS{1'b0}};
        end else begin
            fuse_prog <= 1'b0;
            case (state)
                S_LOAD: begin
                    map <= MUTATION == 5 ? {FW{1'b0}} : fuse_q;
                    ready <= 1'b1;
                    state <= S_IDLE;
                end
                S_IDLE: if (start && !spent) begin
                    busy <= 1'b1;
                    done <= 1'b0;
                    status <= PASS;
                    phase <= 3'd0;
                    second <= 1'b0;
                    row <= {PRW{1'b0}};
                    col <= {PCW{1'b0}};
                    bitmap <= {PR*PC{1'b0}};
                    test_fail <= 1'b0;
                    state <= S_TEST;
                end
                S_TEST: if (req_ready) begin
                    if (!req_write && read_data != expected) begin
                        if (raw) bitmap[cell_index] <= 1'b1;
                        else test_fail <= 1'b1;
                    end
                    if (!element_done) second <= 1'b1;
                    else begin
                        second <= 1'b0;
                        if (!element_last) begin
                            if (!down) begin
                                if (col == last_col) begin
                                    col <= {PCW{1'b0}};
                                    row <= row + 1'b1;
                                end else col <= col + 1'b1;
                            end else begin
                                if (col == {PCW{1'b0}}) begin
                                    col <= last_col;
                                    row <= row - 1'b1;
                                end else col <= col - 1'b1;
                            end
                        end else if (phase == 3'd5) state <= raw ? S_CHECK : S_FIN;
                        else begin
                            phase <= phase + 1'b1;
                            row <= next_down ? last_row : {PRW{1'b0}};
                            col <= next_down ? last_col : {PCW{1'b0}};
                        end
                    end
                end
                S_CHECK: begin
                    mask <= {ROWS{1'b0}};
                    if (!any_main) state <= S_FIN;
                    else if (must_count > rows_free) begin
                        status <= unrepairable_status;
                        state <= S_FIN;
                    end else state <= S_ENUM;
                end
                S_ENUM: begin
                    if (fits) begin
                        fuse_d <= image;
                        fuse_prog <= 1'b1;
                        spent <= 1'b1;
                        status <= REPAIRED;
                        state <= S_FIN;
                    end else if (&mask) begin
                        status <= unrepairable_status;
                        state <= S_FIN;
                    end else mask <= mask + 1'b1;
                end
                S_FIN: begin
                    if (!raw) status <= test_fail ? FAILED : PASS;
                    busy <= 1'b0;
                    done <= 1'b1;
                    state <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
