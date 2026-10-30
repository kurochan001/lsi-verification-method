`timescale 1ns/1ps
module tb_mp_gemm #(
  parameter integer ROWS=4,COLS=4,KBLK=4
);
  import mp_pkg::*;
  localparam integer DEPTH=(ROWS>COLS ? ROWS : COLS)*4*KBLK;
  localparam integer ADDR_W=$clog2(DEPTH);
  localparam integer LEGACY_AW=(ROWS>COLS ? ROWS : COLS)*KBLK>1 ? $clog2((ROWS>COLS ? ROWS : COLS)*KBLK) : 1;
  logic clk,rst_n,start,wr_en,wr_sel,busy,done,error;
  logic [1:0] mode;
  logic [ADDR_W-1:0] wr_addr;
  logic [135:0] wr_data;
  logic [31:0] c_o [ROWS][COLS],legacy_c [ROWS][COLS];
  logic legacy_busy,legacy_done;
  initial begin clk=0;forever #5 clk=~clk;end
  mp_gemm #(.ROWS(ROWS),.COLS(COLS),.KBLK(KBLK)) dut(.*);
  mxfp4_gemm_top #(.ROWS(ROWS),.COLS(COLS),.KBLK(KBLK)) legacy(
    .clk(clk),.rst_n(rst_n),.start(start && mode==FP4),.wr_en(wr_en && mode==FP4 && !busy),
    .wr_sel(wr_sel),.wr_addr(LEGACY_AW'(wr_addr)),.wr_data(wr_data),.busy(legacy_busy),.done(legacy_done),.c_o(legacy_c));
  integer fd,n,op,m,address,expected_error,checks=0,runs=0,x0=0,aborted=0;
  logic [511:0] expected;
  string vectors,wave;
  task automatic check32(input logic [31:0] got,want);
    checks++;if(got!==want) $fatal(1,"MP_GEMM_DATA run=%0d got=%h expected=%h",runs,got,want);
  endtask
  task automatic run_gemm();
    logic [31:0] previous [ROWS][COLS];
    integer cycles,expected_cycles;
    previous=c_o;
    expected_cycles=1+KBLK*(m==0 ? 4 : m==1 ? 2 : 1)+(m==2 ? 6 : 8);
    @(negedge clk);mode=2'(m);start=1;
    @(negedge clk);start=0;mode=3;cycles=1;
    forever begin
      @(posedge clk);#1;cycles++;
      for(integer r=0;r<ROWS;r++) for(integer c=0;c<COLS;c++) check32(c_o[r][c],previous[r][c]);
      if(m==2 && {busy,done}!=={legacy_busy,legacy_done}) $fatal(1,"MP_GEMM_X0_CONTROL");
      if(done) break;
      if(!busy || cycles>expected_cycles) $fatal(1,"MP_GEMM_TIMING");
      @(negedge clk);
      // Start and writes while busy must not alter the captured operation/buffers.
      start=(cycles==3);wr_en=(cycles==3);wr_sel=0;wr_addr=0;wr_data='1;
    end
    if(cycles!=expected_cycles) $fatal(1,"MP_GEMM_LATENCY got=%0d expected=%0d",cycles,expected_cycles);
    @(posedge clk);#1;
    if(error!==1'(expected_error) || busy || done) $fatal(1,"MP_GEMM_COMPLETION error=%b expected=%0d",error,expected_error);
    for(integer r=0;r<ROWS;r++) for(integer c=0;c<COLS;c++) begin
      check32(c_o[r][c],expected[32*(r*COLS+c) +: 32]);
      if(m==2) check32(c_o[r][c],legacy_c[r][c]);
    end
    if(m==2) x0++;
    runs++;
    @(negedge clk);start=0;wr_en=0;
  endtask
  initial begin
    rst_n=0;start=0;wr_en=0;wr_sel=0;wr_addr=0;wr_data=0;mode=FP4;
    if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave)) $fatal(1,"arguments required");
    $dumpfile(wave);$dumpvars(1,tb_mp_gemm);
    fd=$fopen(vectors,"r");if(fd==0) $fatal(1,"vectors missing");
    repeat(3) @(negedge clk);rst_n=1;
    while(!$feof(fd)) begin
      n=$fscanf(fd,"%h %h %h %h %h %h\n",op,m,address,wr_data,expected,expected_error);
      if(n!=6) $fatal(1,"bad matrix row");
      mode=2'(m);
      if(op<2) begin
        wr_en=1;wr_sel=1'(op);wr_addr=ADDR_W'(address);
        @(negedge clk);wr_en=0;
      end else if(op==4) begin
        start=1;@(negedge clk);start=0;
        if(!done || busy || !error) $fatal(1,"MP_GEMM_RESERVED");
        for(integer r=0;r<ROWS;r++) for(integer c=0;c<COLS;c++) check32(c_o[r][c],0);
        @(negedge clk);
      end else begin
        if(op==3) begin
          start=1;@(negedge clk);start=0;
          repeat(2) @(negedge clk);rst_n=0;
          @(negedge clk);rst_n=1;
          repeat(10) begin
            @(posedge clk);#1;
            if(busy || done || error) $fatal(1,"MP_GEMM_ABORT");
            for(integer r=0;r<ROWS;r++) for(integer c=0;c<COLS;c++) check32(c_o[r][c],0);
          end
          aborted++;
        end
        run_gemm();
      end
    end
    $display("MP_GEMM PASS runs=%0d checks=%0d x0=%0d aborted=%0d",runs,checks,x0,aborted);
    $finish;
  end
  initial begin #100_000_000;$fatal(1,"MP matrix timeout");end
endmodule
