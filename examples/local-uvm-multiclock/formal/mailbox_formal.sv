// Free clocks and resets: every clock ratio, every phase and every reset order, including a reset
// change on a clock edge. The state is arbitrary until the first step, which holds both resets.
module mailbox_formal(input wire src_clk,dst_clk,src_rst_n,dst_rst_n,src_valid,dst_ready,
                      input wire [7:0] src_data,input wire [15:0] src_id);
  wire src_ready,src_up,dst_up,dst_valid;wire [7:0] dst_data;wire [15:0] dst_id;
  reset_mailbox dut(.*);
  reg started=0;
  always @($global_clock)started<=1;
  always @*assume(started || (!src_rst_n && !dst_rst_n));
  always @*cover(started && src_valid && src_ready);
  always @*cover(started && dst_valid && dst_ready);
endmodule

// Instantiated inside a copy of reset_mailbox, because Yosys does not resolve hierarchical names.
module mailbox_invariants(input wire src_up,req,present,input wire [1:0] src_release,req_sync,src_seen);
  always @*assert(!src_release[1] || src_release[0]);
  always @*assert(!req || src_up);
  always @*assert(!req_sync[0] || src_seen[0]);
  always @*assert(!req_sync[1] || src_seen[1]);
  always @*assert(!src_seen[1] || src_seen[0]);
  always @*assert(!src_seen[0] || src_up);
  // The goal: dst_valid has the same value without its src_seen[1] term.
  always @*assert(!present || src_seen[1]);
endmodule
