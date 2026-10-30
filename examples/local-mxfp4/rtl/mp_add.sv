// Special-value wrapper around the existing 28-bit GRS FP32 adder.
module mp_add(
  input mp_pkg::term_t a,b,
  output logic [31:0] result
);
  import mp_pkg::*;
  logic sign_bit,zero;
  logic signed [10:0] exponent;
  logic [23:0] significand;
  term_t sum;
  mxfp4_fp32_add_core core(
    .a_sign(a.sign_bit),.a_exp(a.exponent),.a_sig(a.significand),
    .b_sign(b.sign_bit),.b_exp(b.exponent),.b_sig(b.significand),
    .r_sign(sign_bit),.r_exp(exponent),.r_sig(significand),.r_zero(zero),.r_carry_ovf());
  always_comb begin
    sum='0;sum.sign_bit=sign_bit;sum.exponent=exponent;sum.significand=significand;
    if(a.nan || b.nan || (a.inf && b.inf && a.sign_bit!=b.sign_bit)) result=QNAN;
    else if(a.inf) result={a.sign_bit,8'hff,23'b0};
    else if(b.inf) result={b.sign_bit,8'hff,23'b0};
    else if(a.zero && b.zero) result={a.sign_bit & b.sign_bit,31'b0};
    else if(a.zero) result=pack_term(b);
    else if(b.zero) result=pack_term(a);
    else if(zero) result=0;
    else result=pack_term(sum);
  end
endmodule
