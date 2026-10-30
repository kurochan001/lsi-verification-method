// Mode is captured by start. Buffers use row/column * BEATS + beat addressing.
module mp_gemm #(
  parameter integer ROWS=4,COLS=4,KBLK=4,
  parameter integer MAX_DEPTH=(ROWS>COLS ? ROWS : COLS)*4*KBLK,
  parameter integer ADDR_W=MAX_DEPTH>1 ? $clog2(MAX_DEPTH) : 1
)(
  input logic clk,rst_n,start,
  input logic [1:0] mode,
  input logic wr_en,wr_sel,
  input logic [ADDR_W-1:0] wr_addr,
  input logic [135:0] wr_data,
  output logic busy,done,error,
  output logic [31:0] c_o [ROWS][COLS]
);
  import mp_pkg::*;
  localparam integer BW=$clog2(4*KBLK+1);
  localparam integer A_AW=ROWS*4*KBLK>1 ? $clog2(ROWS*4*KBLK) : 1;
  localparam integer B_AW=COLS*4*KBLK>1 ? $clog2(COLS*4*KBLK) : 1;
  typedef enum logic [1:0] {IDLE,LOAD,COMPUTE,DRAIN} state_t;
  state_t state;
  logic [1:0] active_mode;
  logic [BW-1:0] beat_index,beats;
  logic [3:0] drain_count,latency;
  logic rejected;
  logic [135:0] a_mem [ROWS*4*KBLK],b_mem [COLS*4*KBLK];
  logic [135:0] a_stream [ROWS],b_stream [COLS];
  logic [31:0] pe_result [ROWS][COLS];
  logic pe_valid [ROWS][COLS],pe_ready [ROWS][COLS];
  logic pe_scale_error [ROWS][COLS],pe_protocol_error [ROWS][COLS];
  logic all_valid,all_ready,any_error;
  logic feed,last_beat,first_beat,latch_result;
  assign busy=state!=IDLE;
  assign done=rejected || (state==DRAIN && drain_count==latency-1'b1);
  assign latch_result=state==DRAIN && drain_count==latency-1'b1;
  assign feed=state==COMPUTE;
  assign first_beat=beat_index==0;
  assign last_beat=beat_index==beats-1'b1;
  always_comb begin
    all_valid=1;all_ready=1;any_error=0;
    for(integer r=0;r<ROWS;r++) begin
      a_stream[r]=a_mem[r*integer'(beats)+integer'(beat_index)];
      for(integer c=0;c<COLS;c++) begin
        all_valid=all_valid && pe_valid[r][c];
        all_ready=all_ready && pe_ready[r][c];
        any_error=any_error || pe_scale_error[r][c] || pe_protocol_error[r][c];
      end
    end
    for(integer c=0;c<COLS;c++) b_stream[c]=b_mem[c*integer'(beats)+integer'(beat_index)];
  end
  for(genvar r=0;r<ROWS;r++) begin: row
    for(genvar c=0;c<COLS;c++) begin: col
      mp_bdp pe(.clk(clk),.rst_n(rst_n),.in_valid(feed),.first(first_beat),.last(last_beat),
        .out_ready(1'b1),.mode(active_mode),.a_block(a_stream[r]),.b_block(b_stream[c]),
        .in_ready(pe_ready[r][c]),.out_valid(pe_valid[r][c]),.result(pe_result[r][c]),
        .err_scale_mismatch(pe_scale_error[r][c]),.err_protocol(pe_protocol_error[r][c]),.sum8_dbg(),.sum8_valid_dbg());
    end
  end
  // In-flight writes are ignored. Uninitialized buffer locations must be written before start.
  always_ff @(posedge clk) begin
    if(rst_n && wr_en && state==IDLE) begin
      if(wr_sel && integer'(wr_addr)<COLS*4*KBLK) b_mem[B_AW'(wr_addr)]<=wr_data;
      if(!wr_sel && integer'(wr_addr)<ROWS*4*KBLK) a_mem[A_AW'(wr_addr)]<=wr_data;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;active_mode<=FP4;beat_index<=0;beats<=BW'(KBLK);drain_count<=0;latency<=6;rejected<=0;error<=0;
      for(integer r=0;r<ROWS;r++) for(integer c=0;c<COLS;c++) c_o[r][c]<=0;
    end else begin
      rejected<=0;
      case(state)
        IDLE: if(start) begin
          if(mode==3) begin rejected<=1;error<=1;end
          else begin
            active_mode<=mode;beats<=BW'(KBLK*(mode==FP16 ? 4 : mode==FP8 ? 2 : 1));
            latency<=mode==FP4 ? 6 : 8;beat_index<=0;drain_count<=0;state<=LOAD;error<=0;
          end
        end
        LOAD: state<=COMPUTE;
        COMPUTE: begin
          if(!all_ready) begin error<=1;state<=IDLE;rejected<=1;end
          else if(last_beat) begin state<=DRAIN;drain_count<=0;end
          else beat_index<=beat_index+1'b1;
        end
        DRAIN: begin
          if(latch_result) begin
            error<=any_error || !all_valid;
            for(integer r=0;r<ROWS;r++) for(integer c=0;c<COLS;c++) c_o[r][c]<=pe_result[r][c];
            state<=IDLE;
          end else drain_count<=drain_count+1'b1;
        end
        default: state<=IDLE;
      endcase
    end
  end
  a_all_results_valid: assert property (@(posedge clk) disable iff(!rst_n)
    latch_result |-> all_valid) else $fatal(1,"MP_GEMM_PIPELINE");
endmodule
