`timescale 1ns/1ps
// Standalone language-feature calibration. Build this file separately from tb/top.sv.
module top;
  class sampler;
    covergroup measured with function sample(bit policy, bit [1:0] size_code);
      option.per_instance=1;
      cp_policy: coverpoint policy { bins first={0}; bins second={1}; }
      cp_size: coverpoint size_code {
        bins short_size={0}; bins medium_size={1}; bins long_size={2};
      }
      combinations: cross cp_policy, cp_size;
    endgroup
    function new(); measured=new; endfunction
  endclass
  sampler sample_set;
  real instance_percentage, type_percentage, expected;
  initial begin
    sample_set=new;
    sample_set.measured.sample(0,1);
    sample_set.measured.sample(1,1);
    expected=100.0*(1.0+1.0/3.0+2.0/6.0)/3.0;
    instance_percentage=sample_set.measured.get_inst_coverage();
    type_percentage=sample_set.measured.get_coverage();
    $display("CALIBRATION instance=%.6f type=%.6f weighted=%.6f raw=%.6f",
      instance_percentage,type_percentage,expected,100.0*5.0/11.0);
    if(instance_percentage<0 || instance_percentage>100 || type_percentage<0 || type_percentage>100)
      $fatal(1,"coverage API returned an out-of-range percentage");
    $display("CALIBRATION matches_weighted=%0d",
      instance_percentage>=expected-0.000001 && instance_percentage<=expected+0.000001);
    $finish;
  end
endmodule
