// Carries one event at a time from the clk domain to the clk_b domain with a two-phase
// toggle handshake. evt is accepted only while evt_ready is high.
module event_cross #(
  parameter MUTATION = 0
) (
  input  logic clk,
  input  logic rst_n,
  input  logic evt,
  output logic evt_ready,
  input  logic clk_b,
  input  logic rst_b_n,
  output logic note_b
);
  logic req_tgl;
  logic s1, s2, s3, s_extra;
  logic a1, a2;

  assign evt_ready = req_tgl == a2;
  assign note_b    = s2 ^ s3;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      req_tgl <= 1'b0;
      a1 <= 1'b0;
      a2 <= 1'b0;
    end else begin
      if (evt && evt_ready) req_tgl <= !req_tgl;
      a1 <= s2;
      a2 <= a1;
    end
  end

  always_ff @(posedge clk_b) begin
    if (!rst_b_n) begin
      s1 <= 1'b0;
      s_extra <= 1'b0;
      s2 <= 1'b0;
      s3 <= 1'b0;
    end else begin
      s1 <= req_tgl;
      s_extra <= s1;
      s2 <= (MUTATION == 6) ? s_extra : s1;
      s3 <= s2;
    end
  end
endmodule
