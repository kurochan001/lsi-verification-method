// Internal invariants of tagged_queue, asserted (not assumed) next to the bound patterns so
// that induction starts from states the design can actually reach.
  always @(posedge clk) if (rst_n) begin
    i_count:   assert (count <= 3'd4);
    i_select:  assert (wr_sel == 4'b0001 || wr_sel == 4'b0010 || wr_sel == 4'b0100 || wr_sel == 4'b1000);
    i_pointer: assert (wr_ptr - rd_ptr == count[1:0]);
    i_wait:    assert (wait_cnt <= lat && (!empty || wait_cnt == 3'd0));
  end
