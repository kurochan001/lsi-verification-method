`timescale 1ns/1ps
`include "uvm_macros.svh"
package rx_pkg;
  import uvm_pkg::*;
  localparam int RETRIES = 2;
  localparam int TIMEOUT = 8;

  class fatal_to_exit extends uvm_report_catcher;
    function new(string n = "fatal_to_exit"); super.new(n); endfunction
    virtual function action_e catch();
      if (get_severity() == UVM_FATAL) $fatal(1, "UVM_FATAL %s", get_id());
      return THROW;
    endfunction
  endclass

  function automatic void rx_fail(string id, string text);
    $display("CHECK_FAIL %s", id);
    `uvm_fatal(id, text)
  endfunction

  // ---------------------------------------------------------------- items
  // Command side: one command for the DUT, or a reset level.
  class rx_cmd_item extends uvm_sequence_item;
    `uvm_object_utils(rx_cmd_item)
    bit control, rst_n, write;
    bit [7:0] addr, wdata;
    function new(string n = "rx_cmd_item"); super.new(n); endfunction
  endclass

  // What the request monitor saw: the input of the responder sequence.
  class rx_request extends uvm_sequence_item;
    `uvm_object_utils(rx_request)
    bit write;
    bit [7:0] addr, wdata;
    int epoch;
    function new(string n = "rx_request"); super.new(n); endfunction
  endclass

  // One response. The sequence fills the request copy and the read data,
  // callbacks of the driver shape the timing and the injected faults,
  // and the driver reports the outcome back in sent_ok/aborted.
  class rx_rsp_item extends uvm_sequence_item;
    `uvm_object_utils(rx_rsp_item)
    bit write;
    bit [7:0] addr, wdata, rdata;
    int epoch;
    int stall, delay;
    bit err, drop, early, dup;
    bit sent_ok, aborted;
    function new(string n = "rx_rsp_item"); super.new(n); endfunction
    // Hook for derived items: adjust the response before it is driven.
    virtual function void finalize(); endfunction
  endclass

  // Error version selected by a factory override: the top quarter of the
  // address space always answers with an error.
  class rx_err_item extends rx_rsp_item;
    `uvm_object_utils(rx_err_item)
    function new(string n = "rx_err_item"); super.new(n); endfunction
    virtual function void finalize();
      if (addr[7:6] == 2'b11) err = 1;
    endfunction
  endclass

  class rx_obs extends uvm_object;
    `uvm_object_utils(rx_obs)
    int kind, cycle, tries;   // kind: 0 reset level, 1 done, 2 response, 3 accepted request, 4 accepted command
    bit level, write, err, timeout;
    bit [7:0] addr, wdata, rdata;
    function new(string n = "rx_obs"); super.new(n); endfunction
  endclass

  // ---------------------------------------------------------------- memory model
  class rx_memory extends uvm_object;
    `uvm_object_utils(rx_memory)
    bit [7:0] data[int];
    bit fault;
    function new(string n = "rx_memory"); super.new(n); endfunction
    function bit [7:0] read(bit [7:0] addr);
      bit [7:0] value = data.exists(int'(addr)) ? data[int'(addr)] : ~addr;
      return fault && addr[0] ? value ^ 8'h10 : value;
    endfunction
    function void write(bit [7:0] addr, bit [7:0] value); data[int'(addr)] = value; endfunction
  endclass

  // ---------------------------------------------------------------- command agent (active)
  class rx_cmd_driver extends uvm_driver #(rx_cmd_item);
    `uvm_component_utils(rx_cmd_driver)
    virtual rx_if vif;
    function new(string n, uvm_component p); super.new(n, p); endfunction
    task run_phase(uvm_phase phase);
      forever begin
        rx_cmd_item t;
        seq_item_port.get_next_item(t);
        @(negedge vif.clk);
        if (t.control) vif.rst_n = t.rst_n;
        else begin
          int waited = 0;
          vif.cmd_valid = 1; vif.cmd_write = t.write; vif.cmd_addr = t.addr; vif.cmd_wdata = t.wdata;
          do begin
            @(posedge vif.clk); waited++;
            if (waited > 1000) rx_fail("RX_DRAIN", "command was never accepted");
          end while (!vif.rst_n || !vif.cmd_ready);
          @(negedge vif.clk); vif.cmd_valid = 0;
        end
        seq_item_port.item_done();
      end
    endtask
  endclass

  class rx_cmd_agent extends uvm_agent;
    `uvm_component_utils(rx_cmd_agent)
    virtual rx_if vif;
    rx_cmd_driver driver;
    uvm_sequencer #(rx_cmd_item) sequencer;
    function new(string n, uvm_component p); super.new(n, p); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      driver = rx_cmd_driver::type_id::create("driver", this); driver.vif = vif;
      sequencer = new("sequencer", this);
    endfunction
    function void connect_phase(uvm_phase phase); driver.seq_item_port.connect(sequencer.seq_item_export); endfunction
  endclass

  // ---------------------------------------------------------------- responder agent (reactive)
  // Publishes each request once, when it is first presented, and counts resets.
  class rx_request_monitor extends uvm_monitor;
    `uvm_component_utils(rx_request_monitor)
    virtual rx_if vif;
    uvm_analysis_port #(rx_request) requests;
    int epoch;
    bit presented, in_reset;
    function new(string n, uvm_component p); super.new(n, p); requests = new("requests", this); endfunction
    task run_phase(uvm_phase phase);
      forever begin
        @(posedge vif.clk);
        if (!vif.rst_n) begin
          if (!in_reset) epoch++;
          in_reset = 1; presented = 0;
        end else begin
          in_reset = 0;
          if (vif.req_valid && !presented) begin
            rx_request q = rx_request::type_id::create("request");
            q.write = vif.req_write; q.addr = vif.req_addr; q.wdata = vif.req_wdata; q.epoch = epoch;
            presented = 1;
            requests.write(q);
          end
          if (vif.req_valid && vif.req_ready) presented = 0;
        end
      end
    endtask
  endclass

  // The sequencer owns the queue of observed requests and the memory model.
  class rx_rsp_sequencer extends uvm_sequencer #(rx_rsp_item);
    `uvm_component_utils(rx_rsp_sequencer)
    uvm_tlm_analysis_fifo #(rx_request) requests;
    rx_memory memory;
    function new(string n, uvm_component p); super.new(n, p); requests = new("requests", this); endfunction
  endclass

  typedef class rx_rsp_driver;

  // Callback interface of the responder driver.
  class rx_driver_cb extends uvm_callback;
    `uvm_object_utils(rx_driver_cb)
    int unsigned state;
    bit random_on;
    function new(string n = "rx_driver_cb"); super.new(n); endfunction
    function int unsigned draw(int unsigned modulus);
      state = state * 1664525 + 1013904223;
      return (state >> 16) % modulus;
    endfunction
    virtual function void shape(rx_rsp_driver driver, rx_rsp_item item); endfunction
  endclass

  // Acceptance stall and response delay.
  class rx_delay_cb extends rx_driver_cb;
    `uvm_object_utils(rx_delay_cb)
    int armed, stall, delay;
    function new(string n = "rx_delay_cb"); super.new(n); endfunction
    virtual function void shape(rx_rsp_driver driver, rx_rsp_item item);
      if (armed > 0) begin armed--; item.stall = stall; item.delay = delay; end
      else if (random_on) begin item.stall = int'(draw(3)); item.delay = int'(draw(TIMEOUT)); end
    endfunction
  endclass

  // Error responses: the next `armed` items, every item while `forced`, or one in four.
  class rx_error_cb extends rx_driver_cb;
    `uvm_object_utils(rx_error_cb)
    int armed;
    bit forced;
    function new(string n = "rx_error_cb"); super.new(n); endfunction
    virtual function void shape(rx_rsp_driver driver, rx_rsp_item item);
      if (forced) item.err = 1;
      else if (armed > 0) begin armed--; item.err = 1; end
      else if (random_on && draw(4) == 0) item.err = 1;
    endfunction
  endclass

  // No response at all: the requester has to time out.
  class rx_drop_cb extends rx_driver_cb;
    `uvm_object_utils(rx_drop_cb)
    int armed;
    function new(string n = "rx_drop_cb"); super.new(n); endfunction
    virtual function void shape(rx_rsp_driver driver, rx_rsp_item item);
      if (armed > 0) begin armed--; item.drop = 1; end
      else if (random_on && draw(10) == 0) item.drop = 1;
    endfunction
  endclass

  // Protocol violations: a response before the request is accepted, and a
  // second response right after the real one.
  class rx_violation_cb extends rx_driver_cb;
    `uvm_object_utils(rx_violation_cb)
    int early_armed, dup_armed;
    function new(string n = "rx_violation_cb"); super.new(n); endfunction
    virtual function void shape(rx_rsp_driver driver, rx_rsp_item item);
      if (early_armed > 0) begin early_armed--; item.early = 1; end
      else if (random_on && draw(6) == 0) item.early = 1;
      if (dup_armed > 0) begin dup_armed--; item.dup = 1; end
      else if (random_on && draw(6) == 0) item.dup = 1;
    endfunction
  endclass

  class rx_rsp_driver extends uvm_driver #(rx_rsp_item);
    `uvm_component_utils(rx_rsp_driver)
    `uvm_register_cb(rx_rsp_driver, rx_driver_cb)
    virtual rx_if vif;
    rx_request_monitor monitor;
    int items, error_type_items;
    bit aborted;
    function new(string n, uvm_component p); super.new(n, p); endfunction
    // One clock. A reset seen by the monitor since the request ends the item.
    task step(rx_rsp_item t);
      if (!aborted) begin
        @(negedge vif.clk);
        if (monitor.epoch != t.epoch) begin aborted = 1; vif.req_ready = 0; vif.rsp_valid = 0; end
      end
    endtask
    task pulse(rx_rsp_item t, bit err, bit [7:0] rdata);
      if (!aborted) begin vif.rsp_valid = 1; vif.rsp_err = err; vif.rsp_rdata = rdata; end
      step(t);
      if (!aborted) vif.rsp_valid = 0;
    endtask
    task run_phase(uvm_phase phase);
      forever begin
        rx_rsp_item t;
        seq_item_port.get_next_item(t);
        `uvm_do_callbacks(rx_rsp_driver, rx_driver_cb, shape(this, t))
        if (t.early && t.stall < 2) t.stall = 2;
        if (t.delay > TIMEOUT - 1) t.delay = TIMEOUT - 1;
        if (t.drop) t.dup = 0;
        items++;
        if (t.get_type_name() == "rx_err_item") error_type_items++;
        aborted = 0;
        // Every pin changes on a falling edge; the requester samples on the rising edge.
        step(t);
        // Acceptance stall; an early response goes out while the request still waits.
        for (int i = 0; i < t.stall; i++) begin
          if (t.early && i == 0) pulse(t, 0, ~t.addr);
          else step(t);
        end
        if (!aborted) vif.req_ready = 1;
        step(t);
        if (!aborted) vif.req_ready = 0;
        repeat (t.delay) step(t);
        if (!t.drop) begin
          pulse(t, t.err, t.rdata);
          if (t.dup) pulse(t, 0, ~t.addr);
        end
        t.aborted = aborted;
        t.sent_ok = !aborted && !t.drop && !t.err;
        $display("RX_ITEM n=%0d type=%s write=%0d addr=%0d stall=%0d delay=%0d err=%0d drop=%0d early=%0d dup=%0d aborted=%0d",
                 items, t.get_type_name(), t.write, t.addr, t.stall, t.delay, t.err, t.drop, t.early, t.dup, t.aborted);
        seq_item_port.item_done();
      end
    endtask
  endclass

  // Reactive sequence: wait for an observed request, answer it from the
  // memory model, and commit a write only when an OK response went out.
  class rx_responder_seq extends uvm_sequence #(rx_rsp_item);
    `uvm_object_utils(rx_responder_seq)
    `uvm_declare_p_sequencer(rx_rsp_sequencer)
    function new(string n = "rx_responder_seq"); super.new(n); endfunction
    task body();
      forever begin
        rx_request q;
        rx_rsp_item r;
        p_sequencer.requests.get(q);
        r = rx_rsp_item::type_id::create("response");
        start_item(r);
        r.write = q.write; r.addr = q.addr; r.wdata = q.wdata; r.epoch = q.epoch;
        r.rdata = q.write ? 8'h00 : p_sequencer.memory.read(q.addr);
        r.finalize();
        finish_item(r);
        if (r.sent_ok && r.write) p_sequencer.memory.write(r.addr, r.wdata);
      end
    endtask
  endclass

  class rx_responder_agent extends uvm_agent;
    `uvm_component_utils(rx_responder_agent)
    virtual rx_if vif;
    rx_request_monitor monitor;
    rx_rsp_sequencer sequencer;
    rx_rsp_driver driver;
    function new(string n, uvm_component p); super.new(n, p); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      monitor = rx_request_monitor::type_id::create("monitor", this); monitor.vif = vif;
      sequencer = rx_rsp_sequencer::type_id::create("sequencer", this);
      sequencer.memory = rx_memory::type_id::create("memory");
      driver = rx_rsp_driver::type_id::create("driver", this); driver.vif = vif; driver.monitor = monitor;
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);
      monitor.requests.connect(sequencer.requests.analysis_export);
    endfunction
  endclass

  // ---------------------------------------------------------------- checking
  // One passive monitor for all channels, so that the events of one clock
  // edge reach the scoreboard in a fixed order.
  class rx_system_monitor extends uvm_monitor;
    `uvm_component_utils(rx_system_monitor)
    virtual rx_if vif;
    uvm_analysis_port #(rx_obs) observed;
    int cycle, checker_off;
    bit previous_reset;
    function new(string n, uvm_component p); super.new(n, p); observed = new("observed", this); endfunction
    function void publish(int kind);
      rx_obs t = rx_obs::type_id::create("observation");
      t.kind = kind; t.cycle = cycle; t.level = vif.rst_n;
      case (kind)
        1: begin t.err = vif.done_err; t.timeout = vif.done_timeout; t.rdata = vif.done_rdata; t.tries = int'(vif.done_tries); end
        2: begin t.err = vif.rsp_err; t.rdata = vif.rsp_rdata; end
        3: begin t.write = vif.req_write; t.addr = vif.req_addr; t.wdata = vif.req_wdata; end
        4: begin t.write = vif.cmd_write; t.addr = vif.cmd_addr; t.wdata = vif.cmd_wdata; end
        default: ;
      endcase
      $display("RX_OBS kind=%0d cycle=%0d level=%0d write=%0d addr=%0d wdata=%0d rdata=%0d err=%0d timeout=%0d tries=%0d",
               kind, cycle, t.level, t.write, t.addr, t.wdata, t.rdata, t.err, t.timeout, t.tries);
      if (!(checker_off == 1 && kind == 1) && checker_off != 2) observed.write(t);
    endfunction
    task run_phase(uvm_phase phase);
      void'($value$plusargs("CHECKER_OFF=%d", checker_off));
      forever begin
        @(posedge vif.clk); cycle++;
        if (vif.rst_n != previous_reset) begin publish(0); previous_reset = vif.rst_n; end
        if (vif.rst_n) begin
          if (vif.done_valid) publish(1);
          if (vif.rsp_valid) publish(2);
          if (vif.req_valid && vif.req_ready) publish(3);
          if (vif.cmd_valid && vif.cmd_ready) publish(4);
        end
      end
    endtask
  endclass

  // Checks the requester against the bus alone; it does not know what the
  // responder injected. The read data is compared with its own mirror.
  class rx_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(rx_scoreboard)
    uvm_analysis_imp #(rx_obs, rx_scoreboard) observed;
    bit busy, waiting, answered, last_err, is_write;
    bit [7:0] addr, wdata, last_rdata;
    int attempts, accepted_at;
    bit [7:0] mirror[int];
    int commands, completed, cancelled, total_attempts, error_responses, timeouts, spurious, exhausted, retried_ok;
    function new(string n, uvm_component p); super.new(n, p); observed = new("observed", this); endfunction
    function bit [7:0] expected_read(bit [7:0] a);
      return mirror.exists(int'(a)) ? mirror[int'(a)] : ~a;
    endfunction
    function void write(rx_obs t);
      case (t.kind)
        0: if (!t.level && busy) begin cancelled++; busy = 0; waiting = 0; end
        4: begin
          if (busy) rx_fail("RX_ORDER", "command accepted while the previous one is open");
          busy = 1; waiting = 0; answered = 0; attempts = 0; is_write = t.write; addr = t.addr; wdata = t.wdata; commands++;
        end
        3: begin
          if (!busy || waiting) rx_fail("RX_ORDER", "request accepted without a command or before the response");
          if (attempts > 0 && !(answered && last_err)) rx_fail("RX_ORDER", "request repeated without an error response");
          if (t.write != is_write || t.addr != addr || t.wdata != wdata) rx_fail("RX_REQUEST", "request differs from the command");
          attempts++; total_attempts++;
          if (attempts > RETRIES + 1) rx_fail("RX_RETRY", "more attempts than the retry limit");
          waiting = 1; answered = 0; accepted_at = t.cycle;
        end
        2: begin
          if (!waiting) spurious++;
          else begin
            waiting = 0; answered = 1; last_err = t.err; last_rdata = t.rdata;
            if (t.err) error_responses++;
            else if (is_write) mirror[int'(addr)] = wdata;
            else if (t.rdata != expected_read(addr)) rx_fail("RX_MEMORY", "responder read data differs from the mirror");
          end
        end
        1: begin
          if (!busy || attempts == 0) rx_fail("RX_SPURIOUS", "completion without an accepted request");
          if (waiting) begin
            if (!t.timeout || !t.err || t.cycle - accepted_at != TIMEOUT + 1) rx_fail("RX_TIMEOUT", "completion while waiting is not the timeout");
            timeouts++;
          end else begin
            if (!answered) rx_fail("RX_SPURIOUS", "completion without a response");
            if (t.timeout) rx_fail("RX_TIMEOUT", "timeout reported although a response arrived");
            if (last_err && attempts != RETRIES + 1) rx_fail("RX_RETRY", "error reported before the retries were used");
            if (t.err != last_err) rx_fail("RX_RETRY", "completion status differs from the last response");
            if (t.rdata != (is_write ? 8'h00 : last_rdata)) rx_fail("RX_DATA", "completion data differs from the response");
            if (last_err) exhausted++;
            else if (attempts > 1) retried_ok++;
          end
          if (t.tries != attempts) rx_fail("RX_RETRY", "reported number of attempts differs");
          busy = 0; waiting = 0; completed++;
        end
        default: rx_fail("RX_OBSERVER", "unknown observation");
      endcase
    endfunction
  endclass

  class rx_env extends uvm_env;
    `uvm_component_utils(rx_env)
    virtual rx_if vif;
    rx_cmd_agent commands;
    rx_responder_agent responder;
    rx_system_monitor monitor;
    rx_scoreboard scoreboard;
    function new(string n, uvm_component p); super.new(n, p); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(virtual rx_if)::get(this, "", "vif", vif)) `uvm_fatal("RX_CFG", "missing interface")
      commands = rx_cmd_agent::type_id::create("commands", this); commands.vif = vif;
      responder = rx_responder_agent::type_id::create("responder", this); responder.vif = vif;
      monitor = rx_system_monitor::type_id::create("monitor", this); monitor.vif = vif;
      scoreboard = rx_scoreboard::type_id::create("scoreboard", this);
    endfunction
    function void connect_phase(uvm_phase phase); monitor.observed.connect(scoreboard.observed); endfunction
  endclass

  // ---------------------------------------------------------------- stimulus
  class rx_single extends uvm_sequence #(rx_cmd_item);
    `uvm_object_utils(rx_single)
    rx_cmd_item item;
    function new(string n = "rx_single"); super.new(n); endfunction
    task body(); start_item(item); finish_item(item); endtask
  endclass

  class rx_scenario extends uvm_sequence #(uvm_sequence_item);
    `uvm_object_utils(rx_scenario)
    rx_env env;
    rx_delay_cb delay;
    rx_error_cb errors;
    rx_drop_cb drops;
    rx_violation_cb violations;
    int unsigned state;
    int issued, random_commands;
    bit callbacks_off;
    function new(string n = "rx_scenario"); super.new(n); endfunction
    task clocks(int n); repeat (n) @(negedge env.vif.clk); endtask
    task send(rx_cmd_item item);
      rx_single s = rx_single::type_id::create("single");
      s.item = item; s.start(env.commands.sequencer);
    endtask
    task reset_level(bit level);
      rx_cmd_item item = rx_cmd_item::type_id::create("reset");
      item.control = 1; item.rst_n = level; send(item);
    endtask
    task settle();
      for (int i = 0; i < 400; i++) begin
        clocks(1);
        if (env.scoreboard.completed + env.scoreboard.cancelled >= issued) begin clocks(3); return; end
      end
      rx_fail("RX_DRAIN", "issued commands did not complete");
    endtask
    task command(bit write, bit [7:0] addr, bit [7:0] wdata, bit random = 0);
      rx_cmd_item item = rx_cmd_item::type_id::create("command");
      item.write = write; item.addr = addr; item.wdata = wdata; issued++;
      $display("RX_ISSUED n=%0d random=%0d write=%0d addr=%0d wdata=%0d", issued, random, write, addr, wdata);
      send(item);
    endtask
    task random_command();
      state = state * 1664525 + 1013904223;
      command(state[31], {state[25:24], 4'b0, state[17:16]}, state[15:8], 1);
    endtask
    task phase_marker(string name); $display("RX_PHASE name=%s items=%0d", name, env.responder.driver.items); endtask
    task create_callbacks(int unsigned seed);
      delay = rx_delay_cb::type_id::create("delay"); delay.state = seed ^ 32'h1111;
      errors = rx_error_cb::type_id::create("errors"); errors.state = seed ^ 32'h2222;
      drops = rx_drop_cb::type_id::create("drops"); drops.state = seed ^ 32'h3333;
      violations = rx_violation_cb::type_id::create("violations"); violations.state = seed ^ 32'h4444;
    endtask
    task startup();
      reset_level(0); clocks(3); reset_level(1); clocks(2);
    endtask
    task finish_line();
      rx_scoreboard s = env.scoreboard;
      if (s.commands != issued || s.completed + s.cancelled != issued || s.busy) rx_fail("RX_COUNTS", "command, completion and cancellation counts differ");
      $display("RX_COMPLETE commands=%0d completed=%0d cancelled=%0d attempts=%0d errors=%0d timeouts=%0d spurious=%0d exhausted=%0d retried_ok=%0d items=%0d",
               s.commands, s.completed, s.cancelled, s.total_attempts, s.error_responses, s.timeouts, s.spurious, s.exhausted, s.retried_ok, env.responder.driver.items);
      $display("RESULT PASS checks=%0d", issued);
    endtask
  endclass

  // Base scenario: plain responses, then every callback, directed and random.
  class rx_base_scenario extends rx_scenario;
    `uvm_object_utils(rx_base_scenario)
    function new(string n = "rx_base_scenario"); super.new(n); endfunction
    task body();
      rx_rsp_driver driver = env.responder.driver;
      rx_scoreboard s = env.scoreboard;
      int spurious_before, errors_before, timeouts_before;
      create_callbacks(state);
      startup();
      // No callback is registered yet: immediate OK responses from the memory model.
      phase_marker("plain");
      command(0, 8'h21, 8'h00); command(1, 8'h21, 8'h5c); command(0, 8'h21, 8'h00); command(1, 8'h22, 8'ha7); command(0, 8'h22, 8'h00);
      settle();
      if (!callbacks_off) begin
        uvm_callbacks #(rx_rsp_driver, rx_driver_cb)::add(driver, delay);
        uvm_callbacks #(rx_rsp_driver, rx_driver_cb)::add(driver, errors);
        uvm_callbacks #(rx_rsp_driver, rx_driver_cb)::add(driver, drops);
        uvm_callbacks #(rx_rsp_driver, rx_driver_cb)::add(driver, violations);
      end
      phase_marker("directed");
      // Long stall and the latest response that is still in time.
      delay.armed = 1; delay.stall = 3; delay.delay = TIMEOUT - 1;
      command(0, 8'h21, 8'h00); settle();
      // One error, then success: the write is committed once.
      errors.armed = 1; command(1, 8'h30, 8'h11); settle();
      errors.armed = 2; command(1, 8'h31, 8'h22); settle();
      command(0, 8'h30, 8'h00); command(0, 8'h31, 8'h00); settle();
      // Errors until the retries are used up: the write must not be committed.
      errors.forced = 1; command(1, 8'h30, 8'hee); settle(); errors.forced = 0;
      command(0, 8'h30, 8'h00); settle();
      // No response: timeout, and the next command works again.
      drops.armed = 1; command(1, 8'h32, 8'h33); settle();
      command(0, 8'h32, 8'h00); settle();
      // Protocol violations: a response before acceptance, a second response after the real one.
      violations.early_armed = 1; command(0, 8'h21, 8'h00); settle();
      violations.dup_armed = 1; command(0, 8'h22, 8'h00); settle();
      errors.armed = 1; violations.dup_armed = 1; command(1, 8'h33, 8'h44); settle();
      command(0, 8'h33, 8'h00); settle();
      // Reset while the response is outstanding: the command is cancelled.
      delay.armed = 1; delay.stall = 0; delay.delay = TIMEOUT - 1;
      command(0, 8'h21, 8'h00); clocks(3);
      reset_level(0); clocks(2); reset_level(1); clocks(3);
      command(0, 8'h21, 8'h00); settle();
      // Everything at random.
      phase_marker("random");
      delay.random_on = 1; errors.random_on = 1; drops.random_on = 1; violations.random_on = 1;
      repeat (random_commands) random_command();
      settle();
      // callback_mode(0) switches a callback off without removing it.
      phase_marker("quiet");
      void'(errors.callback_mode(0)); void'(drops.callback_mode(0)); void'(violations.callback_mode(0));
      spurious_before = s.spurious; errors_before = s.error_responses; timeouts_before = s.timeouts;
      repeat (4) random_command();
      settle();
      if (!callbacks_off && (s.spurious != spurious_before || s.error_responses != errors_before || s.timeouts != timeouts_before))
        rx_fail("RX_GOALS", "a disabled callback still injected");
      // delete() removes the last one: back to immediate responses.
      phase_marker("deleted");
      if (!callbacks_off) uvm_callbacks #(rx_rsp_driver, rx_driver_cb)::delete(driver, delay);
      repeat (2) random_command();
      settle();
      phase_marker("end");
      if (s.cancelled != 1 || s.timeouts == 0 || s.exhausted == 0 || s.retried_ok == 0 || s.spurious < 3)
        rx_fail("RX_GOALS", "an injected response kind was never observed");
      if (driver.error_type_items != 0) rx_fail("RX_FACTORY", "unexpected item type");
      finish_line();
    endtask
  endclass

  // Scenario for the factory override: no error callback, the item decides.
  class rx_factory_scenario extends rx_scenario;
    `uvm_object_utils(rx_factory_scenario)
    function new(string n = "rx_factory_scenario"); super.new(n); endfunction
    task body();
      rx_rsp_driver driver = env.responder.driver;
      create_callbacks(state);
      startup();
      phase_marker("directed");
      command(1, 8'h10, 8'h3c); command(1, 8'hc5, 8'h99); command(0, 8'hc5, 8'h00); command(0, 8'h10, 8'h00);
      settle();
      phase_marker("random");
      uvm_callbacks #(rx_rsp_driver, rx_driver_cb)::add(driver, delay);
      delay.random_on = 1;
      repeat (random_commands) random_command();
      settle();
      phase_marker("end");
      if (driver.error_type_items != driver.items) rx_fail("RX_FACTORY", "the factory did not create the error item");
      if (env.scoreboard.exhausted < 2) rx_fail("RX_GOALS", "the error region was never reported");
      finish_line();
    endtask
  endclass

  // ---------------------------------------------------------------- tests
  class rx_base_test extends uvm_test;
    `uvm_component_utils(rx_base_test)
    rx_env env;
    function new(string n, uvm_component p); super.new(n, p); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      env = rx_env::type_id::create("env", this);
    endfunction
    virtual function rx_scenario scenario(); return rx_base_scenario::type_id::create("scenario"); endfunction
    task run_phase(uvm_phase phase);
      rx_scenario main = scenario();
      rx_responder_seq responder = rx_responder_seq::type_id::create("responder");
      int seed, fault, off;
      phase.raise_objection(this);
      void'($value$plusargs("SEED=%d", seed));
      void'($value$plusargs("COMMANDS=%d", main.random_commands));
      void'($value$plusargs("MEMORY_FAULT=%d", fault));
      void'($value$plusargs("CALLBACKS_OFF=%d", off));
      main.env = env; main.state = 32'(seed); main.callbacks_off = off != 0;
      env.responder.sequencer.memory.fault = fault != 0;
      fork responder.start(env.responder.sequencer); join_none
      main.start(null);
      phase.drop_objection(this);
    endtask
  endclass

  // The only difference of this test is the factory override.
  class rx_error_test extends rx_base_test;
    `uvm_component_utils(rx_error_test)
    function new(string n, uvm_component p); super.new(n, p); endfunction
    function void build_phase(uvm_phase phase);
      int off;
      super.build_phase(phase);
      void'($value$plusargs("NO_OVERRIDE=%d", off));
      if (off == 0) set_type_override_by_type(rx_rsp_item::get_type(), rx_err_item::get_type());
    endfunction
    virtual function rx_scenario scenario(); return rx_factory_scenario::type_id::create("scenario"); endfunction
  endclass
endpackage
