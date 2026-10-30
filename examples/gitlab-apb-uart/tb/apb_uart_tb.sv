`timescale 1ns/1ps
module apb_uart_tb;
  parameter integer WAIT_CYCLES=0, PARITY=0, DIVISOR=8, MUTATION=0;
  reg clk=0, rst_n=0, psel=0, penable=0, pwrite=0, rxd=1;
  reg [7:0] paddr=0;
  reg [31:0] pwdata=0;
  wire pready, pslverr, txd, irq, tx_ready, rx_available, saved_pe, saved_fe;
  wire [31:0] prdata;
  wire [3:0] mask, pending;
  wire [7:0] rx_snapshot;
  apb_uart #(.WAIT_CYCLES(WAIT_CYCLES), .PARITY(PARITY), .DIVISOR(DIVISOR), .MUTATION(MUTATION)) dut (
    clk, rst_n, psel, penable, pwrite, paddr, pwdata, rxd, pready, pslverr, prdata,
    txd, irq, mask, pending, rx_snapshot, rx_available, saved_pe, saved_fe, tx_ready
  );
  always #5 clk=!clk;
  integer vr, vs, ve, vw, va, vl, receive, vpe, vfe, fields, fd, checks=0, elapsed=0;
  reg [31:0] vd;
  reg [7:0] value;
  reg [3:0] model_mask=0, model_pending=0, before_mask, before_pending, expected_events;
  reg [7:0] model_rx=0, model_tx=0;
  bit model_available=0, model_pe=0, model_fe=0, delayed_tx_done=0;
  integer tx_remaining=0, tx_completed=0, rx_captured=0, rx_reads=0, apb_completed=0, apb_errors=0;
  localparam integer FRAME_CLOCKS=(10+(PARITY != 0))*DIVISOR;
  bit accepted, invalid, ready_expected, before_irq, expected_irq, old_available;
  bit previous_active=0, must_hold=0, previous_done=0, old_write, recovering=0;
  reg [7:0] old_address;
  reg [31:0] old_data, expected_data;
  integer before_active, after_active, old_remaining;
  string vectors, wave;
  task fail(input string label);
    begin
      $display("CHECK_FAIL %s",label);
      $fatal(1,"cycle=%0d addr=%h mask=%h/%h pending=%h/%h rx=%h/%h",checks,paddr,mask,model_mask,pending,model_pending,rx_snapshot,model_rx);
    end
  endtask
  function automatic bit frame_bit(input reg [7:0] data, input integer index);
    bit p;
    begin
      p=PARITY==2;
      for(integer b=0;b<8;b=b+1) if(data[b]) p=!p;
      if(index==0) frame_bit=0;
      else if(index<=8) frame_bit=data[index-1];
      else if(index==9 && PARITY!=0) frame_bit=p;
      else frame_bit=1;
    end
  endfunction
  task data_cover(input reg [7:0] data,input string direction);
    begin
      if(data==0) $display("COVER %s/data-zero",direction);
      if(data==255) $display("COVER %s/data-ones",direction);
      if(data==85) $display("COVER %s/data-alternating",direction);
      if(data==1) $display("COVER %s/data-lsb",direction);
      if(data==128) $display("COVER %s/data-msb",direction);
    end
  endtask
  task cycle;
    begin
      @(negedge clk);
      rst_n=vr;psel=vs;penable=ve;pwrite=vw;paddr=va;pwdata=vd;rxd=vl;
      #1;
      accepted=0;invalid=0;
      if(rst_n) begin
        if(must_hold && (!psel || !penable || paddr!==old_address || pwrite!==old_write || (pwrite && pwdata!==old_data))) fail("APB_MASTER_STABILITY");
        if(psel && penable && !previous_active) fail("APB_MASTER_SETUP");
        if(previous_done && psel && penable) fail("APB_MASTER_BACK_TO_BACK");
        ready_expected=psel && penable && elapsed>=WAIT_CYCLES;
        accepted=ready_expected;
        invalid=0;
        case(paddr)
          0,16: invalid=0;
          4,20: invalid=pwrite;
          8: invalid=!pwrite || tx_remaining!=0;
          12: invalid=pwrite || !model_available;
          default: invalid=1;
        endcase
        if(pready!==ready_expected) fail("APBUART_READY");
        if(pslverr!==(accepted && invalid)) fail("APBUART_ERROR_RESPONSE");
        if(accepted && !pwrite) begin
          expected_data=0;
          if(!invalid) case(paddr)
            0: expected_data={28'b0,model_mask};
            4: expected_data={28'b0,model_fe,model_pe,model_available,(tx_remaining==0)};
            12: expected_data={24'b0,model_rx};
            16: expected_data={28'b0,model_pending};
            20: expected_data=32'h55415254;
          endcase
          if(prdata!==expected_data) fail("APBUART_READ_DATA");
        end
      end else if(pready!==1'b0 || pslverr!==1'b0) fail("APBUART_RESET_RESPONSE");
      before_mask=model_mask;before_pending=model_pending;old_available=model_available;
      old_remaining=tx_remaining;
      before_irq=0;before_active=0;
      for(integer b=0;b<4;b=b+1) if(before_mask[b] && before_pending[b]) begin before_irq=1;before_active=before_active+1;end
      expected_events=0;
      if(delayed_tx_done) expected_events[0]=1;
      if(receive) begin expected_events[1]=1;expected_events[2]=vpe;expected_events[3]=vfe;end
      @(posedge clk);
      if(!rst_n) begin
        model_mask=0;model_pending=0;model_rx=0;model_available=0;model_pe=0;model_fe=0;
        tx_remaining=0;delayed_tx_done=0;elapsed=0;
      end else begin
        delayed_tx_done=tx_remaining==1;
        if(tx_remaining>0) begin
          tx_remaining=tx_remaining-1;
          if(tx_remaining==0) begin tx_completed=tx_completed+1;end
        end
        if(accepted) begin
          apb_completed=apb_completed+1;
          if(invalid) apb_errors=apb_errors+1;
          else begin
            if(pwrite && paddr==0) model_mask=pwdata[3:0];
            if(pwrite && paddr==8) begin model_tx=pwdata[7:0];tx_remaining=FRAME_CLOCKS;end
            if(!pwrite && paddr==12) begin model_available=0;rx_reads=rx_reads+1;end
          end
        end
        // Per-bit event priority; expectations never use DUT UART/event probes.
        for(integer b=0;b<4;b=b+1) begin
          if(accepted && !invalid && pwrite && paddr==16 && pwdata[b]) model_pending[b]=0;
          if(expected_events[b]) model_pending[b]=1;
        end
        if(receive) begin model_rx=value;model_available=1;model_pe=vpe;model_fe=vfe;rx_captured=rx_captured+1;end
        if(psel && !penable) elapsed=0;
        else if(psel && penable) elapsed=elapsed+1;
      end
      #1;checks=checks+1;
      if(mask!==model_mask) fail("APBUART_MASK");
      if(pending!==model_pending) fail("APBUART_PENDING");
      if(rx_snapshot!==model_rx) fail("APBUART_RX_DATA");
      if(rx_available!==model_available || saved_pe!==model_pe || saved_fe!==model_fe) fail("APBUART_RX_STATE");
      if(tx_ready!==(tx_remaining==0)) fail("APBUART_TX_READY");
      if(tx_remaining==0) begin if(txd!==1) fail("APBUART_TX_IDLE");end
      else if(txd!==frame_bit(model_tx,(FRAME_CLOCKS-tx_remaining)/DIVISOR)) begin
        if((FRAME_CLOCKS-tx_remaining)/DIVISOR>=1 && (FRAME_CLOCKS-tx_remaining)/DIVISOR<=8) fail("APBUART_TX_DATA");
        else fail("APBUART_TX_FRAME");
      end
      expected_irq=0;after_active=0;
      for(integer b=0;b<4;b=b+1) if(model_mask[b] && model_pending[b]) begin expected_irq=1;after_active=after_active+1;end
      if(irq!==expected_irq) fail("APBUART_IRQ");
      // Credit observations only after all bus, serial, register and IRQ checks.
      if(!rst_n) begin
        if(old_remaining>0) $display("COVER reset/active-tx");
        if(before_irq) $display("COVER reset/active-irq");
        recovering=recovering || old_remaining>0 || before_irq;
      end else begin
        if(recovering && expected_irq && |expected_events) begin $display("COVER reset/recovery");recovering=0;end
        if(delayed_tx_done) begin $display("COVER transfer/tx-complete");data_cover(model_tx,"tx");end
        if(receive && old_remaining>0) $display("COVER transfer/duplex");
        if(receive && old_available && !(accepted && !invalid && !pwrite && paddr==12)) $display("COVER rx/overwrite");
        if(receive && accepted && !invalid && !pwrite && paddr==12) $display("COVER rx/read-and-new");
        if(accepted && !invalid && !pwrite && paddr==12) begin $display("COVER transfer/rx-read");end
        if(receive) data_cover(value,"rx");
        if(expected_events[3] && model_mask[3]) $display("COVER error/framing-irq");
        if(expected_events[2] && model_mask[2]) $display("COVER error/parity-irq");
        if(psel && !penable && |expected_events) $display("COVER event/setup");
        if(psel && penable && !accepted && |expected_events) $display("COVER event/wait");
        if(accepted && invalid && |expected_events) $display("COVER event/error-response");
        if(previous_done && psel && !penable) $display("COVER bus/back-to-back");
        for(integer b=0;b<4;b=b+1) begin
          if(expected_events[b] && !before_mask[b] && model_pending[b]) $display("COVER irq/masked-event");
          if(accepted && !invalid && pwrite && paddr==16 && before_pending[b])
            $display("COVER cross/bit%0d/mask%0d/clear%0d/event%0d",b,before_mask[b],pwdata[b],expected_events[b]);
          if(accepted && !invalid && pwrite && paddr==0) begin
            if(before_pending[b] && !before_mask[b] && model_mask[b]) $display("COVER irq/unmask-pending");
            if(before_pending[b] && before_mask[b] && !model_mask[b]) $display("COVER irq/remask-pending");
            if(expected_events[b] && !before_mask[b] && model_mask[b]) $display("COVER simultaneous/enable-event");
            if(expected_events[b] && before_mask[b] && !model_mask[b]) $display("COVER simultaneous/disable-event");
          end
        end
        if(accepted && !invalid && pwrite && paddr==16) begin
          if(before_irq && !expected_irq) $display("COVER irq/clear-release");
          if(before_active>1 && after_active==1) $display("COVER irq/partial-clear");
          if(before_active==1 && after_active==0) $display("COVER irq/last-clear");
        end
        if(accepted && invalid) begin
          if(paddr==8 && pwrite) $display("COVER bus/error-busy");
          else if(paddr==12 && !pwrite) $display("COVER bus/error-empty");
          else if(paddr==8) $display("COVER bus/error-direction");
          else if(paddr==4 || paddr==12 || paddr==20) $display("COVER bus/error-readonly");
          else if(paddr[1:0]!=0) $display("COVER bus/error-unaligned");
          else $display("COVER bus/error-unmapped");
        end
      end
      previous_active=rst_n && psel;must_hold=rst_n && psel && (!penable || !accepted);previous_done=rst_n && accepted;
      old_address=paddr;old_write=pwrite;old_data=pwdata;
    end
  endtask
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"Missing VECTORS");
    if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,apb_uart_tb);end
    fd=$fopen(vectors,"r");if(!fd) $fatal(1,"Cannot open vectors");
    while(!$feof(fd)) begin
      fields=$fscanf(fd,"%d %d %d %d %h %h %d %d %h %d %d\n",vr,vs,ve,vw,va,vd,vl,receive,value,vpe,vfe);
      if(fields!=11) fail("APBUART_VECTOR_FORMAT");
      cycle();
    end
    $fclose(fd);
    if(tx_remaining!=0 || delayed_tx_done) fail("APBUART_INCOMPLETE");
    $display("METRICS tx_completed=%0d rx_captured=%0d rx_reads=%0d apb_completed=%0d apb_errors=%0d",tx_completed,rx_captured,rx_reads,apb_completed,apb_errors);
    $display("RESULT PASS checks=%0d",checks);$finish;
  end
endmodule
