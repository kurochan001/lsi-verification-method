// Teaching stream width converter: one word of 2*W bits in, two beats of W bits out,
// low half first. It holds one word and takes the next one in the cycle the high half leaves.
// MUTATION is only for demonstrating what the checks find; it is not for production use.
module width_downsizer #(
  parameter integer W = 8,
  parameter integer MUTATION = 0
) (
  input wire clk,
  input wire rst_n,
  input wire s_valid,
  output wire s_ready,
  input wire [2*W-1:0] s_data,
  output wire m_valid,
  input wire m_ready,
  output wire [W-1:0] m_data
);
  reg [2*W-1:0] word;
  reg busy;
  reg phase;  // 0: the low half is next, 1: the high half is next

  wire [W-1:0] low = word[W-1:0];
  wire [W-1:0] high = word[2*W-1:W];
  wire fire = m_valid && m_ready;
  wire last = fire && phase;
  // 5: a word whose low half is zero is never offered.
  wire hidden = MUTATION == 5 && !phase && low == {W{1'b0}};
  // 4: the high half is wrong only for words whose low half is all ones.
  wire [W-1:0] flip = {{(W-1){1'b0}}, MUTATION == 4 && low == {W{1'b1}}};
  // 2: the next word is taken although the high half has not left.
  assign s_ready = !busy || (MUTATION == 2 ? (m_valid && phase) : last);
  assign m_valid = busy && !hidden;
  // 1: the halves leave in the wrong order.
  assign m_data = (phase ^ (MUTATION == 1)) ? high ^ flip : low;

  always @(posedge clk) begin
    if (!rst_n) begin
      word <= {(2*W){1'b0}};
      busy <= 1'b0;
      phase <= 1'b0;
    end else begin
      // 3: the phase does not advance while the next word is kept waiting.
      if (fire && !(MUTATION == 3 && !phase && s_valid && !s_ready)) phase <= !phase;
      if (s_valid && s_ready) begin
        // 6: a word equal to the one just sent is dropped.
        if (MUTATION == 6 && busy && s_data == word) busy <= 1'b0;
        else begin
          word <= s_data;
          busy <= 1'b1;
          phase <= 1'b0;
        end
      end else if (last) busy <= 1'b0;
    end
  end
endmodule
