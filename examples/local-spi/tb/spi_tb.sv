`timescale 1ns/1ps
module spi_tb;
  parameter integer CPOL=0,CPHA=0,HALF_DIV=2,MUTATION=0;
  reg clk=0,rst_n=0,start=0,miso=0;
  reg [7:0] tx_data=0,vtx,vrx;
  wire sclk,cs_n,mosi,busy,done;
  wire [7:0] rx_data;
  bit allow_done=0,previous_done=0,recovering=0;
  integer fd,fields,mode,injection,gap,checks=0,transfers=0,aborts=0;
  string vectors,wave;
  spi_master #(.CPOL(CPOL),.CPHA(CPHA),.HALF_DIV(HALF_DIV),.MUTATION(MUTATION)) dut(
    clk,rst_n,start,tx_data,miso,sclk,cs_n,mosi,busy,done,rx_data);
  always #5 clk=!clk;
  task fail(input string label);
    begin $display("CHECK_FAIL %s",label);$fatal(1,"command=%0d sclk=%b cs=%b busy=%b rx=%h",checks,sclk,cs_n,busy,rx_data);end
  endtask
  always @(posedge clk) begin
    #1;
    if(!rst_n) begin
      if(sclk!==CPOL[0] || cs_n!==1 || busy!==0 || done!==0 || rx_data!==0 || mosi!==0) fail("SPI_RESET");
      previous_done=0;
    end else begin
      if((^{sclk,cs_n,mosi,busy,done,rx_data})===1'bx) fail("SPI_UNKNOWN");
      if(done && (!allow_done || previous_done)) fail("SPI_UNEXPECTED_DONE");
      if(!busy && (cs_n!==1 || sclk!==CPOL[0])) fail("SPI_IDLE");
      previous_done=done;
    end
  end
  task transfer(input reg [7:0] tx,input reg [7:0] rx,input bit inject,input integer clocks_to_check);
    integer edge_count,tx_index,rx_index;
    reg [7:0] previous_rx,slave_observed;
    reg clock_expected;
    begin
      @(negedge clk);
      if(busy) fail("SPI_NOT_READY");
      previous_rx=rx_data;slave_observed=0;
      start=1;tx_data=tx;miso=CPHA==0 ? rx[7] : !rx[7];
      @(posedge clk);#2;
      if(busy!==1 || cs_n!==0 || sclk!==CPOL[0] || mosi!==tx[7]) fail("SPI_START");
      for(integer tick=1;tick<=clocks_to_check;tick=tick+1) begin
        @(negedge clk);start=0;
        if(inject && tick==HALF_DIV+1) begin start=1;tx_data=~tx;end
        edge_count=(tick-1)/HALF_DIV;
        if(CPHA==0) begin
          rx_index=edge_count/2;if(rx_index>7) rx_index=7;
          miso=rx[7-rx_index];
        end else if(edge_count>=1) begin
          rx_index=(edge_count-1)/2;if(rx_index>7) rx_index=7;
          miso=rx[7-rx_index];
        end
        allow_done=clocks_to_check==17*HALF_DIV && tick==17*HALF_DIV;
        @(posedge clk);#2;
        edge_count=tick/HALF_DIV;if(edge_count>16) edge_count=16;
        clock_expected=CPOL[0] ^ (edge_count%2);
        if(sclk!==clock_expected) fail("SPI_CLOCK");
        if(cs_n!==(tick==17*HALF_DIV)) fail("SPI_CS");
        if(busy!==(tick<17*HALF_DIV) || done!==(tick==17*HALF_DIV)) fail("SPI_COMPLETION");
        if(CPHA==0) tx_index=edge_count/2;
        else tx_index=edge_count==0 ? 0 : (edge_count-1)/2;
        if(tx_index>7) tx_index=7;
        if(mosi!==tx[7-tx_index]) fail("SPI_MOSI");
        if(tick<17*HALF_DIV && rx_data!==previous_rx) fail("SPI_RX_EARLY");
        if(tick<=16*HALF_DIV && tick%HALF_DIV==0 &&
           ((CPHA==0 && edge_count%2==1) || (CPHA==1 && edge_count%2==0)))
          slave_observed={slave_observed[6:0],mosi};
        if(tick==17*HALF_DIV && (rx_data!==rx || slave_observed!==tx)) fail("SPI_RX");
      end
      if(clocks_to_check==17*HALF_DIV) transfers=transfers+1;
    end
  endtask
  task data_cover(input reg [7:0] value,input string direction);
    begin
      if(value==0) $display("COVER %s/data-zero",direction);
      if(value==255) $display("COVER %s/data-ones",direction);
      if(value==85) $display("COVER %s/data-alternating",direction);
      if(value==1) $display("COVER %s/data-lsb",direction);
      if(value==128) $display("COVER %s/data-msb",direction);
    end
  endtask
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"Missing VECTORS");
    if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,spi_tb);end
    repeat(3) @(negedge clk);rst_n=1;
    fd=$fopen(vectors,"r");if(!fd) $fatal(1,"Cannot open vectors");
    while(!$feof(fd)) begin
      fields=$fscanf(fd,"%h %h %h %h %h\n",mode,vtx,vrx,injection,gap);
      if(fields!=5) fail("SPI_VECTOR_FORMAT");
      if(mode==0) begin
        transfer(vtx,vrx,injection!=0,17*HALF_DIV);
        data_cover(vtx,"tx");data_cover(vrx,"rx");
        $display("COVER transfer/duplex");$display("COVER clock/all-edges");
        if(injection!=0) $display("COVER busy/ignored");
        if(recovering) begin $display("COVER reset/recovery");recovering=0;end
      end else if(mode==1) begin
        transfer(vtx,vrx,0,5*HALF_DIV);
        @(negedge clk);rst_n=0;start=0;miso=0;allow_done=0;
        repeat(2) @(negedge clk);rst_n=1;
        repeat(20*HALF_DIV) @(negedge clk);
        aborts=aborts+1;recovering=1;$display("COVER reset/active");
      end else fail("SPI_VECTOR_MODE");
      @(negedge clk);allow_done=0;
      repeat(gap+1) @(negedge clk);
      checks=checks+1;
    end
    $fclose(fd);allow_done=0;
    repeat(20*HALF_DIV) @(negedge clk);
    if(busy || !cs_n || sclk!==CPOL[0]) fail("SPI_IDLE");
    $display("COVER idle/lines");
    $display("COUNT transfers=%0d",transfers);$display("COUNT aborts=%0d",aborts);
    $display("RESULT PASS checks=%0d",checks);$finish;
  end
endmodule
