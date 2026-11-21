// Applies the pattern library to the two designs without editing them.
// The helper-register forms are bound for every tool. The assertion forms are bound only for
// simulation, because the open-source Yosys front end reads no concurrent assertion.
// Yosys does not read "bind" either: the formal runner rewrites each statement below into an
// instance at the end of the target module, so this file stays the single list of bindings.
bind tagged_queue pat_hold_aux #(.W(DATA_W + 2)) u_hold_aux (.clk(clk), .rst_n(rst_n), .valid(out_valid), .ready(out_ready), .data({out_id, out_data}));
bind tagged_queue pat_onehot_aux #(.W(4)) u_onehot_aux (.clk(clk), .rst_n(rst_n), .en(1'b1), .vec(wr_sel));
bind tagged_queue pat_within_aux #(.N(LAT + 1)) u_within_aux (.clk(clk), .rst_n(rst_n), .req(in_fire), .ack(out_valid));
bind tagged_queue pat_nodup_aux #(.IDS(4), .IW(2)) u_nodup_aux (.clk(clk), .rst_n(rst_n), .start(in_fire), .done(out_fire), .tag(in_id), .dtag(out_id));
bind tagged_queue pat_pipe_aux #(.W(DATA_W + 2), .LAT(LAT + 1)) u_pipe_aux (.clk(clk), .rst_n(rst_n), .valid(in_fire && empty), .q_valid(out_valid), .data({in_id, in_data}), .q_data({out_id, out_data}));
bind tagged_queue pat_order_aux #(.W(DATA_W + 2), .CW(3), .FREE_PICK(1)) u_order_aux (.clk(clk), .rst_n(rst_n), .push(in_fire), .pop(out_fire), .din({in_id, in_data}), .dout({out_id, out_data}));
bind event_cross pat_cross_aux #(.N(3)) u_cross_aux (.clk(clk), .rst_n(rst_n), .accept(evt && evt_ready), .clk_b(clk_b), .rst_b_n(rst_b_n), .note(note_b));
`ifndef FORMAL
bind tagged_queue pat_hold_sva #(.W(DATA_W + 2)) u_hold_sva (.clk(clk), .rst_n(rst_n), .valid(out_valid), .ready(out_ready), .data({out_id, out_data}));
bind tagged_queue pat_onehot_sva #(.W(4)) u_onehot_sva (.clk(clk), .rst_n(rst_n), .en(1'b1), .vec(wr_sel));
bind tagged_queue pat_within_sva #(.N(LAT + 1)) u_within_sva (.clk(clk), .rst_n(rst_n), .req(in_fire), .ack(out_valid));
bind tagged_queue pat_nodup_sva #(.IDS(4), .IW(2)) u_nodup_sva (.clk(clk), .rst_n(rst_n), .start(in_fire), .done(out_fire), .tag(in_id), .dtag(out_id));
bind tagged_queue pat_pipe_sva #(.W(DATA_W + 2), .LAT(LAT + 1)) u_pipe_sva (.clk(clk), .rst_n(rst_n), .valid(in_fire && empty), .q_valid(out_valid), .data({in_id, in_data}), .q_data({out_id, out_data}));
`endif
