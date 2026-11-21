// Proof harnesses that follow one freely chosen item through a FIFO, an AXI4-Stream
// FIFO and a stream width converter.
//
// The tag is an arbitrary constant (anyconst). Which accepted item carrying that value
// is followed is also arbitrary (anyseq pick). A position counter holds the number of
// items that must leave before it. One proof therefore covers every value at every
// position, without a reference queue for all items.
//
// Wires named x_* are the internal registers of the unmodified design under test.
// Open-source Yosys has neither bind nor hierarchical references, so run.py flattens
// the design and connects them. Left unconnected they are free inputs and the
// auxiliary invariants fail, so a missing connection cannot pass silently.

// Existing synchronous FIFO: read data appears one cycle after the read is accepted.
module fifo_integrity #(
  parameter integer DEPTH = 3,
  parameter integer MUTATION = 0,
  parameter integer AUXILIARY = 1,
  parameter integer AVAILABLE = 1
) (
  input wire clk,
  input wire rst_n,
  input wire past_valid
);
  localparam integer W = 8;
  localparam integer CW = $clog2(DEPTH + 1);
  localparam integer PW = DEPTH > 1 ? $clog2(DEPTH) : 1;
  (* anyseq *) wire wr_en;
  (* anyseq *) wire rd_en;
  (* anyseq *) wire [W-1:0] wr_data;
  (* anyseq *) wire pick;
  (* anyconst *) wire [W-1:0] tag;
  wire [W-1:0] rd_data;
  wire rd_valid, full, empty;
  wire [CW-1:0] count;
  sync_fifo #(.WIDTH(W), .DEPTH(DEPTH), .MUTATION(MUTATION)) dut (
    clk, rst_n, wr_en, rd_en, wr_data, rd_data, rd_valid, full, empty, count
  );
  (* keep *) wire [PW-1:0] x_rd_ptr;
  (* keep *) wire [PW-1:0] x_wr_ptr;
  (* keep *) wire [DEPTH*W-1:0] x_memory;

  // What the interface shows: an accepted write and an accepted read.
  wire push = rst_n && wr_en && !full;
  wire pop = rst_n && rd_en && !empty;
  reg [CW-1:0] items;   // accepted and not yet read, counted at the interface only
  reg tracking;
  reg [CW-1:0] ahead;   // items that must be read before the followed one
  reg expect_tag;       // the followed item was read in the previous cycle
  wire start = push && pick && !tracking && wr_data == tag;
  wire leave = pop && tracking && ahead == 0;
  wire [CW:0] slot = {1'b0, ahead} + {{(CW+1-PW){1'b0}}, x_rd_ptr};
  wire [CW:0] wrapped = slot >= DEPTH ? slot - DEPTH : slot;
  wire [CW:0] write_slot = {1'b0, count} + {{(CW+1-PW){1'b0}}, x_rd_ptr};
  wire [CW:0] write_wrapped = write_slot >= DEPTH ? write_slot - DEPTH : write_slot;

  always @(posedge clk) begin
    if (!rst_n) begin
      items <= 0;
      tracking <= 0;
      ahead <= 0;
      expect_tag <= 0;
    end else begin
      case ({push, pop})
        2'b10: items <= items + 1'b1;
        2'b01: items <= items - 1'b1;
        default: items <= items;
      endcase
      expect_tag <= leave;
      if (start) begin
        tracking <= 1;
        ahead <= pop ? items - 1'b1 : items;
      end else if (pop && tracking) begin
        if (ahead == 0) tracking <= 0;
        else ahead <= ahead - 1'b1;
      end
    end
    if (past_valid) begin
      if (expect_tag) ap_content: assert (rd_valid && rd_data == tag);
      if (pop) ap_no_spurious: assert (items != 0);
      if (push) ap_no_overflow: assert (items != DEPTH);
      cp_start: cover (start);
      cp_wait: cover (pop && tracking && ahead != 0);
      cp_exit: cover (expect_tag);
      cp_last_slot: cover (start && !pop && items == DEPTH - 1);
      cp_through: cover (start && pop);
    end
  end
  generate if (AVAILABLE) begin : available
    always @(posedge clk) if (past_valid && items != 0) ap_available: assert (!empty);
  end endgenerate
  generate if (AUXILIARY) begin : auxiliary
    always @(posedge clk) if (past_valid) begin
      ai_count: assert (count == items && items <= DEPTH);
      ai_pointer: assert (x_rd_ptr < DEPTH && x_wr_ptr < DEPTH && write_wrapped[PW-1:0] == x_wr_ptr);
      if (tracking) ai_slot: assert (ahead < items && x_memory[wrapped[PW-1:0]*W +: W] == tag);
    end
  end endgenerate
endmodule

// Existing AXI4-Stream packet FIFO: a beat is TLAST, TKEEP and TDATA together.
module axis_integrity #(
  parameter integer DEPTH = 2,
  parameter integer MUTATION = 0,
  parameter integer AUXILIARY = 1,
  parameter integer AVAILABLE = 1,
  parameter integer SIDEBAND = 1
) (
  input wire clk,
  input wire rst_n,
  input wire past_valid
);
  localparam integer A = $clog2(DEPTH);
  localparam integer B = 37;
  (* anyseq *) wire s_valid;
  (* anyseq *) wire m_ready;
  (* anyseq *) wire [31:0] s_data;
  (* anyseq *) wire [3:0] s_keep;
  (* anyseq *) wire s_last;
  (* anyseq *) wire pick;
  (* anyconst *) wire [B-1:0] tag;
  wire s_ready, m_valid, m_last;
  wire [31:0] m_data;
  wire [3:0] m_keep;
  axis_packet_fifo #(.DEPTH(DEPTH), .MUTATION(MUTATION)) dut (
    clk, rst_n, s_valid, s_data, s_keep, s_last, s_ready, m_valid, m_data, m_keep, m_last, m_ready
  );
  (* keep *) wire [A-1:0] x_head;
  (* keep *) wire [A-1:0] x_tail;
  (* keep *) wire [A:0] x_count;
  (* keep *) wire [DEPTH*B-1:0] x_memory;

  wire push = rst_n && s_valid && s_ready;
  wire pop = rst_n && m_valid && m_ready;
  reg [A:0] items;
  reg tracking;
  reg [A:0] ahead;
  wire start = push && pick && !tracking && {s_last, s_keep, s_data} == tag;
  wire front = rst_n && m_valid && tracking && ahead == 0;
  wire [A-1:0] slot = x_head + ahead[A-1:0];
  wire [A-1:0] write_slot = x_head + x_count[A-1:0];

  always @(posedge clk) begin
    if (!rst_n) begin
      items <= 0;
      tracking <= 0;
      ahead <= 0;
    end else begin
      case ({push, pop})
        2'b10: items <= items + 1'b1;
        2'b01: items <= items - 1'b1;
        default: items <= items;
      endcase
      if (start) begin
        tracking <= 1;
        ahead <= pop ? items - 1'b1 : items;
      end else if (pop && tracking) begin
        if (ahead == 0) tracking <= 0;
        else ahead <= ahead - 1'b1;
      end
    end
    if (past_valid) begin
      // Checked whenever the followed beat is offered, so it must also stay unchanged while it waits.
      if (front) ap_content: assert (SIDEBAND ? {m_last, m_keep, m_data} == tag : m_data == tag[31:0]);
      if (pop) ap_no_spurious: assert (items != 0);
      // This FIFO takes a beat while full when one leaves in the same cycle.
      if (push) ap_no_overflow: assert (items != DEPTH || pop);
      cp_start: cover (start);
      cp_wait: cover (pop && tracking && ahead != 0);
      cp_exit: cover (front && m_ready);
      cp_sparse_last: cover (front && m_ready && tag[36] && tag[35:32] == 4'b0011);
      cp_through: cover (start && pop);
    end
  end
  generate if (AVAILABLE) begin : available
    always @(posedge clk) if (past_valid && rst_n && items != 0) ap_available: assert (m_valid);
  end endgenerate
  generate if (AUXILIARY) begin : auxiliary
    always @(posedge clk) if (past_valid && rst_n) begin
      ai_count: assert (x_count == items && items <= DEPTH);
      ai_pointer: assert (write_slot == x_tail);
      if (tracking) ai_slot: assert (ahead < items && x_memory[slot*B +: B] == tag);
    end
  end endgenerate
endmodule

// Stream width converter of this example: the position is the half of the word.
module width_integrity #(
  parameter integer MUTATION = 0,
  parameter integer AUXILIARY = 1,
  parameter integer AVAILABLE = 1
) (
  input wire clk,
  input wire rst_n,
  input wire past_valid
);
  localparam integer W = 8;
  (* anyseq *) wire s_valid;
  (* anyseq *) wire m_ready;
  (* anyseq *) wire [2*W-1:0] s_data;
  (* anyseq *) wire pick;
  (* anyconst *) wire [2*W-1:0] tag;
  wire s_ready, m_valid;
  wire [W-1:0] m_data;
  width_downsizer #(.W(W), .MUTATION(MUTATION)) dut (
    clk, rst_n, s_valid, s_ready, s_data, m_valid, m_ready, m_data
  );
  (* keep *) wire x_busy;
  (* keep *) wire x_phase;
  (* keep *) wire [2*W-1:0] x_word;

  wire accept = rst_n && s_valid && s_ready;
  wire pop = rst_n && m_valid && m_ready;
  reg [1:0] beats;      // output beats owed for the accepted words
  reg tracking;
  reg [1:0] ahead;      // beats of earlier words that must leave first
  reg half;             // 0: the low half of the followed word is next, 1: the high half
  wire [1:0] after_pop = pop ? beats - 1'b1 : beats;
  wire start = accept && pick && !tracking && s_data == tag;
  wire front = m_valid && tracking && ahead == 0;

  always @(posedge clk) begin
    if (!rst_n) begin
      beats <= 0;
      tracking <= 0;
      ahead <= 0;
      half <= 0;
    end else begin
      beats <= accept ? after_pop + 2'd2 : after_pop;
      if (start) begin
        tracking <= 1;
        ahead <= after_pop;
        half <= 0;
      end else if (pop && tracking) begin
        if (ahead != 0) ahead <= ahead - 1'b1;
        else if (!half) half <= 1;
        else tracking <= 0;
      end
    end
    if (past_valid) begin
      if (front) ap_content: assert (m_data == (half ? tag[2*W-1:W] : tag[W-1:0]));
      if (pop) ap_no_spurious: assert (beats != 0);
      // The converter holds one word.
      if (accept) ap_no_overflow: assert (after_pop == 0);
      cp_low: cover (front && m_ready && !half);
      cp_high: cover (front && m_ready && half && tag[2*W-1:W] != tag[W-1:0]);
      cp_handoff: cover (start && pop);
      cp_stall: cover (front && !m_ready && half);
    end
  end
  generate if (AVAILABLE) begin : available
    always @(posedge clk) if (past_valid && beats != 0) ap_available: assert (m_valid);
  end endgenerate
  generate if (AUXILIARY) begin : auxiliary
    always @(posedge clk) if (past_valid) begin
      ai_state: assert (beats == (!x_busy ? 2'd0 : x_phase ? 2'd1 : 2'd2));
      if (tracking) ai_slot: assert (ahead == 0 && x_busy && x_word == tag && x_phase == half);
    end
  end endgenerate
endmodule

module data_integrity_formal #(
  parameter integer TARGET = 0,     // 0: FIFO, 1: AXI4-Stream FIFO, 2: width converter
  parameter integer DEPTH = 3,
  parameter integer MUTATION = 0,
  parameter integer AUXILIARY = 1,  // assert the invariants that make the induction step go through
  parameter integer AVAILABLE = 1,  // assert that held data is offered
  parameter integer SIDEBAND = 1    // AXI4-Stream: compare TKEEP and TLAST as well as TDATA
) (
  input wire clk,
  input wire rst_n
);
  reg past_valid = 0;
  always @(posedge clk) begin
    past_valid <= 1;
    if (!past_valid) as_initial_reset: assume (!rst_n);
  end
  generate
    if (TARGET == 0) begin : fifo
      fifo_integrity #(.DEPTH(DEPTH), .MUTATION(MUTATION), .AUXILIARY(AUXILIARY), .AVAILABLE(AVAILABLE))
        check (clk, rst_n, past_valid);
    end
    if (TARGET == 1) begin : axis
      axis_integrity #(.DEPTH(DEPTH), .MUTATION(MUTATION), .AUXILIARY(AUXILIARY), .AVAILABLE(AVAILABLE),
                       .SIDEBAND(SIDEBAND)) check (clk, rst_n, past_valid);
    end
    if (TARGET == 2) begin : width
      width_integrity #(.MUTATION(MUTATION), .AUXILIARY(AUXILIARY), .AVAILABLE(AVAILABLE))
        check (clk, rst_n, past_valid);
    end
  endgenerate
endmodule
