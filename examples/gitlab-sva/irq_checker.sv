`timescale 1ns/1ps
module irq_checker (
  input logic clk, rst_n, checker_enabled, launch,
  input logic event_accept, clear_accept, pend, irq_en, irq,
  output bit failed
);
  bit history_valid = 0;
  initial failed = 0;
  always @(posedge clk) history_valid <= 1;

  ap_set_wins: assert property (@(posedge clk) disable iff (!checker_enabled || !rst_n)
    (launch && event_accept && clear_accept) |=> pend)
    else begin $display("CHECK_FAIL IRQ_SET_WINS"); failed = 1; end
  ap_set_only: assert property (@(posedge clk) disable iff (!checker_enabled || !rst_n)
    (launch && event_accept && !clear_accept) |=> pend)
    else begin $display("CHECK_FAIL IRQ_SET_ONLY"); failed = 1; end
  ap_clear_only: assert property (@(posedge clk) disable iff (!checker_enabled || !rst_n)
    (launch && !event_accept && clear_accept) |=> !pend)
    else begin $display("CHECK_FAIL IRQ_CLEAR_ONLY"); failed = 1; end
  ap_hold: assert property (@(posedge clk) disable iff (!checker_enabled || !rst_n)
    (launch && !event_accept && !clear_accept) |=> $stable(pend))
    else begin $display("CHECK_FAIL IRQ_HOLD"); failed = 1; end
  // Synchronous reset is itself checked; do not disable this assertion on reset.
  ap_reset: assert property (@(posedge clk) disable iff (!checker_enabled)
    (launch && !rst_n) |=> !pend)
    else begin $display("CHECK_FAIL IRQ_RESET"); failed = 1; end
  ap_irq: assert property (@(posedge clk) disable iff (!checker_enabled || !rst_n)
    irq == (pend && irq_en))
    else begin $display("CHECK_FAIL IRQ_OUTPUT"); failed = 1; end

  cp_set_wins_seen: cover property (@(posedge clk)
    checker_enabled && launch && rst_n && event_accept && clear_accept)
    $display("COVER cp_set_wins_seen");
  cp_set_wins_done: cover property (@(posedge clk)
    checker_enabled && rst_n && history_valid && $past(checker_enabled && launch && rst_n && event_accept && clear_accept) && pend)
    $display("COVER cp_set_wins_done");
  cp_set_only_seen: cover property (@(posedge clk)
    checker_enabled && launch && rst_n && event_accept && !clear_accept)
    $display("COVER cp_set_only_seen");
  cp_set_only_done: cover property (@(posedge clk)
    checker_enabled && rst_n && history_valid && $past(checker_enabled && launch && rst_n && event_accept && !clear_accept) && pend)
    $display("COVER cp_set_only_done");
  cp_clear_only_seen: cover property (@(posedge clk)
    checker_enabled && launch && rst_n && !event_accept && clear_accept)
    $display("COVER cp_clear_only_seen");
  cp_clear_only_done: cover property (@(posedge clk)
    checker_enabled && rst_n && history_valid && $past(checker_enabled && launch && rst_n && !event_accept && clear_accept) && !pend)
    $display("COVER cp_clear_only_done");
  cp_hold_seen: cover property (@(posedge clk)
    checker_enabled && launch && rst_n && !event_accept && !clear_accept)
    $display("COVER cp_hold_seen");
  cp_hold_done: cover property (@(posedge clk)
    checker_enabled && rst_n && history_valid && $past(checker_enabled && launch && rst_n && !event_accept && !clear_accept) && $stable(pend))
    $display("COVER cp_hold_done");
  cp_reset_pending_seen: cover property (@(posedge clk)
    checker_enabled && launch && !rst_n && pend)
    $display("COVER cp_reset_pending_seen");
  cp_reset_done: cover property (@(posedge clk)
    checker_enabled && history_valid && $past(checker_enabled && launch && !rst_n && pend) && !pend)
    $display("COVER cp_reset_done");
  cp_masked_pending: cover property (@(posedge clk)
    checker_enabled && rst_n && pend && !irq_en && !irq)
    $display("COVER cp_masked_pending");
  cp_unmasked_pending: cover property (@(posedge clk)
    checker_enabled && rst_n && pend && irq_en && irq)
    $display("COVER cp_unmasked_pending");
endmodule
