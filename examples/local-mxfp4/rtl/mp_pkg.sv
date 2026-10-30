// Appendix B implementation: integer arithmetic only; no real/shortreal in RTL.
package mp_pkg;
  localparam logic [1:0] FP16=0, FP8=1, FP4=2;
  localparam logic [31:0] QNAN=32'h7fc00000;
  typedef struct packed {
    logic nan, inf, zero, sign_bit;
    logic signed [10:0] exponent;
    logic [23:0] significand;
  } term_t;

  function automatic logic [63:0] rshift_rne(input logic [63:0] value,input integer shift);
    logic [63:0] retained;
    logic guard_bit,sticky;
    retained=0;guard_bit=0;sticky=0;
    if(shift<=0) retained=value<<(-shift);
    else begin
      if(shift<=64) guard_bit=value[shift-1];
      for(integer i=0;i<64;i++) if(i<shift-1) sticky=sticky|value[i];
      if(shift<64) retained=value>>shift;
      if(guard_bit && (sticky || retained[0])) retained=retained+1'b1;
    end
    return retained;
  endfunction

  // Normalize an exact fixed-point coefficient. MXFP4 never needs rounding;
  // MXFP8 uses all 42 coefficient bits before its explicit block rounding.
  function automatic term_t normalize(input logic signed [63:0] coefficient,input integer exp2);
    term_t t;
    logic [63:0] magnitude,rounded;
    integer leading,exponent;
    t='0;t.sign_bit=coefficient[63];t.zero=(coefficient==0);
    magnitude=coefficient[63] ? 64'(-coefficient) : 64'(coefficient);
    leading=0;
    for(integer i=0;i<64;i++) if(magnitude[i]) leading=i;
    rounded=rshift_rne(magnitude,leading-23);
    exponent=leading+exp2+127;
    if(rounded[24]) begin rounded=rounded>>1;exponent++;end
    t.exponent=11'(exponent);t.significand=rounded[23:0];
    return t;
  endfunction

  function automatic logic [31:0] pack_term(input term_t t);
    if(t.nan) return QNAN;
    if(t.inf) return {t.sign_bit,8'hff,23'b0};
    if(t.zero) return {t.sign_bit,31'b0};
    if(t.exponent>=255) return {t.sign_bit,8'hff,23'b0};
    if(t.exponent<=0) return {t.sign_bit,31'b0};
    return {t.sign_bit,t.exponent[7:0],t.significand[22:0]};
  endfunction

  function automatic term_t unpack32(input logic [31:0] bits);
    term_t t;
    t='0;t.sign_bit=bits[31];t.exponent=$signed({3'b0,bits[30:23]});
    t.significand={1'b1,bits[22:0]};t.zero=(bits[30:23]==0); // DAZ at FP32 boundaries
    t.nan=(bits[30:23]==255 && bits[22:0]!=0);
    t.inf=(bits[30:0]==31'h7f800000);
    return t;
  endfunction

  function automatic logic signed [4:0] e4m3_m(input logic [7:0] code);
    logic signed [4:0] magnitude;
    magnitude=code[6:3]==0 ? $signed({2'b0,code[2:0]}) : $signed({1'b0,1'b1,code[2:0]});
    return code[7] ? -magnitude : magnitude;
  endfunction
  function automatic integer e4m3_e(input logic [7:0] code);
    return code[6:3]==0 ? -6 : integer'(code[6:3])-7;
  endfunction

  function automatic logic [31:0] fp16_product(input logic [15:0] a,b);
    logic [10:0] ma,mb;
    logic [21:0] product;
    integer ea,eb;
    term_t t;
    if((a[14:10]==31 && a[9:0]!=0)||(b[14:10]==31 && b[9:0]!=0)) return QNAN;
    if(a[14:10]==31 || b[14:10]==31) begin
      if(a[14:0]==0 || b[14:0]==0) return QNAN;
      return {a[15]^b[15],8'hff,23'b0};
    end
    ma={a[14:10]!=0,a[9:0]};mb={b[14:10]!=0,b[9:0]};
    product=ma*mb;
    ea=a[14:10]==0 ? -24 : integer'(a[14:10])-25;
    eb=b[14:10]==0 ? -24 : integer'(b[14:10])-25;
    t=normalize($signed({42'b0,product}),ea+eb);t.sign_bit=a[15]^b[15];
    return pack_term(t);
  endfunction

  function automatic logic [15:0] fp16_cast(input logic [31:0] bits);
    logic [63:0] sig,rounded;
    integer exponent;
    if(bits[30:23]==255) return bits[22:0]!=0 ? 16'h7e00 : {bits[31],5'h1f,10'b0};
    if(bits[30:23]==0) return {bits[31],15'b0}; // Even the largest FP32 subnormal is below half a FP16 LSB.
    sig={40'b0,1'b1,bits[22:0]};exponent=integer'(bits[30:23])-127;
    if(exponent< -14) begin
      rounded=rshift_rne(sig,-exponent-1); // target quantum 2^-24
      return {bits[31],15'(rounded)};      // carry reaches smallest normal 0x0400
    end
    rounded=rshift_rne(sig,13);
    if(rounded[11]) begin rounded=rounded>>1;exponent++;end
    if(exponent>15) return {bits[31],5'h1f,10'b0};
    return {bits[31],5'(exponent+15),rounded[9:0]};
  endfunction

  function automatic logic [7:0] quantize_e4m3(input logic [31:0] bits,input logic [7:0] scale);
    logic [63:0] sig,rounded;
    integer exponent;
    if(bits[30:23]==0) return {bits[31],7'b0}; // Encoder DAZ, not element DAZ.
    sig={40'b0,1'b1,bits[22:0]};exponent=integer'(bits[30:23])-integer'(scale);
    if(exponent< -6) begin
      rounded=rshift_rne(sig,14-exponent); // round on the common 2^-9 subnormal grid
      return {bits[31],7'(rounded)};
    end
    rounded=rshift_rne(sig,20);
    if(rounded[4]) begin rounded=rounded>>1;exponent++;end
    if(exponent>8 || (exponent==8 && rounded>14)) return {bits[31],7'h7e};
    return {bits[31],4'(exponent+7),rounded[2:0]};
  endfunction
endpackage
