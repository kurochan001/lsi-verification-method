// Byte-wide register port that assembles frames and raises interrupts.
// All outputs are registered; a transfer is one clock with req high.
module frame_port #(parameter int MUTATION = 0) (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       req,
    input  logic       write,
    input  logic [2:0] addr,
    input  logic [7:0] wdata,
    input  logic       alarm,
    output logic       ack,
    output logic [7:0] rdata,
    output logic       irq,
    output logic       frame_valid,
    output logic [7:0] frame_head,
    output logic [7:0] frame_len,
    output logic [7:0] frame_sum
);
    localparam logic [2:0] CTRL = 3'd0, DATA = 3'd1, INDEX = 3'd2, VALUE = 3'd3, STATUS = 3'd4, ENABLE = 3'd5;

    logic       in_frame;
    logic [7:0] count, sum, head;
    logic [1:0] index;
    logic [7:0] last_len, last_sum, frames, errors;
    logic [2:0] status, enable;

    wire wr = req && write;
    wire sof = wr && addr == CTRL && wdata[0];
    wire eof = wr && addr == CTRL && !wdata[0] && wdata[1];
    wire push = wr && addr == DATA;
    wire done = eof && in_frame;
    wire bad = (sof && in_frame) || (eof && !in_frame) || (push && !in_frame);
    wire clear = wr && addr == STATUS;

    // Events win over a clear that arrives in the same clock.
    wire [2:0] set_bits = {bad, alarm, done};
    wire [2:0] clear_bits = MUTATION == 2 ? {3{clear}} : {3{clear}} & wdata[2:0];
    wire [2:0] status_next = MUTATION == 4 ? (status | set_bits) & ~clear_bits
                                           : (status & ~clear_bits) | set_bits;

    logic [7:0] selected;
    always_comb begin
        case (MUTATION == 3 ? {index[1], index[1] ^ index[0]} : index)
            2'd0: selected = last_len;
            2'd1: selected = last_sum;
            2'd2: selected = frames;
            default: selected = errors;
        endcase
    end

    logic [7:0] read_value;
    always_comb begin
        case (addr)
            CTRL: read_value = {7'b0, in_frame};
            DATA: read_value = count;
            INDEX: read_value = {6'b0, index};
            VALUE: read_value = selected;
            STATUS: read_value = {5'b0, status};
            ENABLE: read_value = {5'b0, enable};
            default: read_value = 8'h00;
        endcase
    end

    assign irq = |(status & enable);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            ack <= 1'b0; rdata <= 8'h00; frame_valid <= 1'b0;
            frame_head <= 8'h00; frame_len <= 8'h00; frame_sum <= 8'h00;
            in_frame <= 1'b0; count <= 8'h00; sum <= 8'h00; head <= 8'h00;
            index <= 2'd0; last_len <= 8'h00; last_sum <= 8'h00; frames <= 8'h00; errors <= 8'h00;
            status <= 3'b000; enable <= 3'b000;
        end else begin
            ack <= req;
            rdata <= req && !write ? read_value : 8'h00;
            frame_valid <= done;
            status <= status_next;
            if (bad) errors <= errors + 8'd1;
            if (sof) begin
                in_frame <= 1'b1; count <= 8'h00;
                if (MUTATION != 1) sum <= 8'h00;
            end
            if (push && in_frame) begin
                count <= count + 8'd1; sum <= sum + wdata;
                if (count == 8'h00) head <= wdata;
            end
            if (done) begin
                in_frame <= 1'b0; last_len <= count; last_sum <= sum; frames <= frames + 8'd1;
                frame_head <= head; frame_len <= count; frame_sum <= sum;
            end
            if (wr && addr == INDEX) index <= wdata[1:0];
            if (wr && addr == ENABLE) enable <= wdata[2:0];
        end
    end
endmodule
