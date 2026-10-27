`timescale 1ns/1ps
module crc_tb;
 parameter MUTATION=0,INIT=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,s_valid=0,s_last=0,check_enable=0,m_ready=0;reg[31:0]s_data=0;reg[3:0]s_keep=0;reg[7:0]expected_crc=0;wire s_ready,m_valid,m_error;wire[7:0]m_crc;reg partial=0,recovering=0,active_check=0;
 crc #(.MUTATION(MUTATION),.INIT(INIT)) dut(.*);
 integer fd,n,checks=0;reg[63:0]v[0:11];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");
 $dumpfile(wave);$dumpvars(0,crc_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad row");
 rst_n=v[0];
 s_valid=v[1];
 s_data=v[2];
 s_keep=v[3];
 s_last=v[4];
 check_enable=v[5];
 expected_crc=v[6];
 m_ready=v[7];
 #1;
 if(s_ready!==v[8][0] || m_valid!==v[9][0])fail("CRC_CONTROL");
 if(m_valid && m_crc!==v[10][7:0])fail("CRC_DATA");
 if(m_valid && m_error!==v[11][0])fail("CRC_ERROR");
 if(!rst_n)begin if(partial)$display("COVER reset/partial");partial=0;recovering=1;end
 if(s_valid && s_ready)begin
 if(s_keep==15)$display("COVER packet/full");if(s_keep!=0 && s_keep!=15)$display("COVER packet/sparse");
 if(s_last)active_check=check_enable;
 if(s_last && !partial && s_keep==0)$display("COVER packet/empty");partial=!s_last;
 end
 if(m_valid && !m_ready)$display("COVER output/held");
 if(m_valid && m_ready)begin if(m_error)$display("COVER packet/check-bad");else if(active_check)$display("COVER packet/check-good");if(recovering)begin $display("COVER reset/recovery");recovering=0;end end
 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
