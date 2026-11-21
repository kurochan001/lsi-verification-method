// Plays one recorded trace into every pattern checker. The simulator and SBY both read this
// module, so both tools see identical clocks and data.
// Row (13 bits): clk edge, clk_b edge, reset released, v0, v1, d0[3:0], d1[3:0].
// Each row lasts two steps of gclk: the selected clocks are low, then high.
module trace_harness #(parameter LEN = 48) (
  input logic gclk,
  input logic [2:0] sel
);
  logic [12:0] rom [0:LEN-1];
  logic [15:0] step;
  initial step = 16'd0;
`ifdef FORMAL
  initial $readmemh("trace.hex", rom);
`else
  string trace_file;
  initial begin
    if (!$value$plusargs("TRACE=%s", trace_file)) $fatal(1, "TRACE missing");
    $readmemh(trace_file, rom);
  end
`endif
`ifdef FORMAL
  // In the formal run every solver step is one tick, so step numbers map directly to rows.
  (* gclk *) reg tick_clk;
`else
  wire tick_clk = gclk;
`endif
  always @(posedge tick_clk) if (step != 16'(2 * LEN - 1)) step <= step + 16'd1;

  wire [12:0] row = rom[step[15:1]];
  wire        clk   = row[12] && step[0];
  wire        clk_b = row[11] && step[0];
  wire        rst   = row[10];
  wire        v0    = row[9];
  wire        v1    = row[8];
  wire [3:0]  d0    = row[7:4];
  wire [3:0]  d1    = row[3:0];

  wire r_hold   = rst && sel == 3'd1;
  wire r_onehot = rst && sel == 3'd2;
  wire r_within = rst && sel == 3'd3;
  wire r_nodup  = rst && sel == 3'd4;
  wire r_pipe   = rst && sel == 3'd5;
  wire r_order  = rst && sel == 3'd6;
  wire r_cross  = rst && sel == 3'd7;

  pat_hold_aux   #(.W(4))            u_hold_aux   (.clk(clk), .rst_n(r_hold), .valid(v0), .ready(v1), .data(d0));
  pat_onehot_aux #(.W(4))            u_onehot_aux (.clk(clk), .rst_n(r_onehot), .en(v0), .vec(d0));
  pat_within_aux #(.N(3))            u_within_aux (.clk(clk), .rst_n(r_within), .req(v0), .ack(v1));
  pat_nodup_aux  #(.IDS(4), .IW(2))  u_nodup_aux  (.clk(clk), .rst_n(r_nodup), .start(v0), .done(v1), .tag(d0[1:0]), .dtag(d1[1:0]));
  pat_pipe_aux   #(.W(4), .LAT(2))   u_pipe_aux   (.clk(clk), .rst_n(r_pipe), .valid(v0), .q_valid(v1), .data(d0), .q_data(d1));
  pat_order_aux  #(.W(4), .CW(4))    u_order_aux  (.clk(clk), .rst_n(r_order), .push(v0), .pop(v1), .din(d0), .dout(d1));
  pat_cross_aux  #(.N(3))            u_cross_aux  (.clk(clk), .rst_n(r_cross), .accept(v0), .clk_b(clk_b), .rst_b_n(r_cross), .note(v1));
`ifndef FORMAL
  pat_hold_sva   #(.W(4))            u_hold_sva   (.clk(clk), .rst_n(r_hold), .valid(v0), .ready(v1), .data(d0));
  pat_onehot_sva #(.W(4))            u_onehot_sva (.clk(clk), .rst_n(r_onehot), .en(v0), .vec(d0));
  pat_within_sva #(.N(3))            u_within_sva (.clk(clk), .rst_n(r_within), .req(v0), .ack(v1));
  pat_nodup_sva  #(.IDS(4), .IW(2))  u_nodup_sva  (.clk(clk), .rst_n(r_nodup), .start(v0), .done(v1), .tag(d0[1:0]), .dtag(d1[1:0]));
  pat_pipe_sva   #(.W(4), .LAT(2))   u_pipe_sva   (.clk(clk), .rst_n(r_pipe), .valid(v0), .q_valid(v1), .data(d0), .q_data(d1));
  pat_order_sva  #(.W(4), .CW(4))    u_order_sva  (.clk(clk), .rst_n(r_order), .push(v0), .pop(v1), .din(d0), .dout(d1));
`endif
endmodule
