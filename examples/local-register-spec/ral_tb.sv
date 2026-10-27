module ral_tb;
 import uvm_pkg::*;import rdl_pkg::*;
 rdl_block model;int bad=0;
 initial begin
 void'($value$plusargs("BAD_RAL=%d",bad));model=new("model");model.build();
 if(bad==1)model.cfg.value.set_reset(0);
 if(bad==2)model.pending.value.set_volatility(0);
 model.reset();
 if(model.cfg.value.is_volatile() || model.idreg.value.is_volatile() || !model.pending.value.is_volatile())begin $display("CHECK_FAIL RDL_RAL");$fatal(1,"generated RAL volatility differs from hardware update contract");end
 if(model.cfg.get_address()!=0 || model.cfg.get_reset()!=18 || model.cfg.value.get_n_bits()!=8 || model.cfg.value.get_access()!="RW" || model.idreg.value.get_n_bits()!=32 || model.idreg.get_address()!=4 || model.idreg.get_reset()!=32'h52444c31 || model.idreg.value.get_access()!="RO" || model.pending.get_reset()!=0 || model.pending.get_address()!=8 || model.pending.value.get_n_bits()!=4 || model.pending.value.get_access()!="W1C")begin $display("CHECK_FAIL RDL_RAL");$fatal(1,"generated RAL differs from independent contract");end
 $display("COUNT views=1");$display("RESULT PASS checks=1");$finish;
 end
endmodule
