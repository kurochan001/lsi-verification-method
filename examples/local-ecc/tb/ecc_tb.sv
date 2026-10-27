`timescale 1ns/1ps
module ecc_tb;
  parameter integer MUTATION=0;
  reg [7:0] data_in, expected_data;
  reg [12:0] received, expected_encoded, expected_code, mask;
  reg expected_corrected, expected_uncorrectable;
  wire [12:0] encoded, corrected_code;
  wire [7:0] data_out;
  wire corrected, uncorrectable;
  integer fd,fields,checks=0,weight,clean=0,single=0,double_errors=0,triple=0,four=0;
  string vectors,wave;
  secded #(.MUTATION(MUTATION)) dut(data_in,received,encoded,corrected_code,data_out,corrected,uncorrectable);
  task fail(input string label);
    begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d data=%h received=%h encoded=%h output=%h",checks,data_in,received,encoded,data_out);end
  endtask
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"Missing VECTORS");
    if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,ecc_tb);end
    fd=$fopen(vectors,"r");if(!fd) $fatal(1,"Cannot open vectors");
    while(!$feof(fd)) begin
      fields=$fscanf(fd,"%h %h %h %h %h %h %h\n",data_in,received,expected_encoded,expected_code,expected_data,expected_corrected,expected_uncorrectable);
      if(fields!=7) fail("ECC_VECTOR_FORMAT");
      #1;
      if(encoded!==expected_encoded) fail("ECC_ENCODE");
      if(corrected!==expected_corrected || uncorrectable!==expected_uncorrectable) fail("ECC_FLAGS");
      if(corrected_code!==expected_code) fail("ECC_CORRECTION");
      if(data_out!==expected_data) fail("ECC_DATA");
      mask=received ^ expected_encoded;weight=0;
      for(integer bitno=0;bitno<13;bitno=bitno+1) if(mask[bitno]) weight=weight+1;
      case(weight)
        0:begin clean=clean+1;$display("COVER error/clean");end
        1:begin
          single=single+1;
          for(integer b=0;b<13;b=b+1) if(mask[b]) $display("COVER single/bit%0d",b);
        end
        2:begin
          double_errors=double_errors+1;
          for(integer a=0;a<13;a=a+1) for(integer b=a+1;b<13;b=b+1)
            if(mask[a] && mask[b]) $display("COVER double/bit%0d/bit%0d",a,b);
        end
        3:begin triple=triple+1;$display("LIMIT triple/miscorrection output=%h",data_out);end
        4:begin four=four+1;$display("LIMIT four/undetected output=%h",data_out);end
        default:fail("ECC_UNPLANNED_WEIGHT");
      endcase
      if(data_in==0) $display("COVER data/zero");
      if(data_in==255) $display("COVER data/ones");
      if(data_in==85) $display("COVER data/alternating");
      if(data_in==1) $display("COVER data/lsb");
      if(data_in==128) $display("COVER data/msb");
      checks=checks+1;
    end
    $fclose(fd);
    $display("COUNT clean=%0d",clean);$display("COUNT single=%0d",single);
    $display("COUNT double=%0d",double_errors);$display("COUNT triple=%0d",triple);$display("COUNT four=%0d",four);
    $display("RESULT PASS checks=%0d",checks);$finish;
  end
endmodule
