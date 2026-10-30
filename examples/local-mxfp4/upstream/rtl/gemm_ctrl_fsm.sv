// -----------------------------------------------------------------------------
// gemm_ctrl_fsm
//   GEMM 制御 FSM。IDLE / LOAD / COMPUTE / DRAIN の 4 状態。
//   仕様書 8.3 / 8.4 / 8.5 / 8.7 節
//
//   タイミング (KBLK = 4, LAT = 6 の例。仕様書 図9):
//     cycle : 0    1    2    3    4    5    6 .. 10   11
//     state : IDLE LOAD COMP COMP COMP COMP DRN..DRN  DRN
//     kblk  : -    -    0    1    2    3    -  ..  -   -
//     valid : 0    0    1    1    1    1    0  ..  0   0
//     first : -    -    1    0    0    0    -  ..  -   -
//     last  : -    -    0    0    0    1    -  ..  -   -
//     done  : 0    0    0    0    0    0    0  ..  0   1
//   総サイクル数は LOAD(1) + KBLK + LAT。
//
//   LAT は mxfp4_bdp の実パイプライン段数と機械的に一致させること
//   (仕様書 8.5 節 / 12 章 注意 10)。
// -----------------------------------------------------------------------------
module gemm_ctrl_fsm #(
  parameter int KBLK = 8,
  parameter int LAT  = 6,
  // 以下は導出パラメータ。上書きしないこと。
  //   KBLK = 1 のとき $clog2(1) = 0 となり幅 0 の宣言になるため下限 1 を置く。
  parameter int KB_W = (KBLK > 1) ? $clog2(KBLK) : 1,
  parameter int DC_W = $clog2(LAT + 1)
) (
  input  logic            clk,
  input  logic            rst_n,
  input  logic            start,
  output logic            pe_valid,
  output logic            pe_first,
  output logic            pe_last,
  output logic [KB_W-1:0] a_kblk,
  output logic [KB_W-1:0] b_kblk,
  output logic            c_latch,
  output logic            done,
  output logic            busy
);

  typedef enum logic [1:0] {
    IDLE = 2'b00,
    LOAD = 2'b01,
    COMP = 2'b10,
    DRN  = 2'b11
  } state_e;

  state_e state, next;

  logic [KB_W-1:0] kblk;
  logic [DC_W-1:0] drain_cnt;

  // ---- 状態レジスタ ----
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) state <= IDLE;
    else        state <= next;
  end

  // ---- kblk / drain_cnt カウンタ ----
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      kblk      <= '0;
      drain_cnt <= '0;
    end else begin
      unique case (state)
        LOAD: begin
          kblk      <= '0;
          drain_cnt <= '0;
        end
        COMP:    kblk      <= (kblk == KB_W'(KBLK-1)) ? kblk : kblk + KB_W'(1);
        DRN:     drain_cnt <= drain_cnt + DC_W'(1);
        default: ;
      endcase
    end
  end

  // ---- 次状態 ----
  always_comb begin
    next = state;
    unique case (state)
      IDLE: if (start)                        next = LOAD;
      LOAD:                                   next = COMP;
      COMP: if (kblk == KB_W'(KBLK-1))        next = DRN;
      DRN:  if (drain_cnt == DC_W'(LAT-1))    next = IDLE;
      default:                                next = IDLE;
    endcase
  end

  // ---- 出力 (Moore + kblk による修飾) ----
  always_comb begin
    pe_valid = 1'b0;
    pe_first = 1'b0;
    pe_last  = 1'b0;
    c_latch  = 1'b0;
    done     = 1'b0;
    busy     = 1'b0;
    a_kblk   = kblk;
    b_kblk   = kblk;
    unique case (state)
      IDLE: ;
      LOAD: busy = 1'b1;
      COMP: begin
        busy     = 1'b1;
        pe_valid = 1'b1;
        pe_first = (kblk == '0);
        pe_last  = (kblk == KB_W'(KBLK-1));
      end
      DRN: begin
        busy = 1'b1;
        if (drain_cnt == DC_W'(LAT-1)) begin
          c_latch = 1'b1;
          done    = 1'b1;
        end
      end
      default: ;
    endcase
  end

endmodule
