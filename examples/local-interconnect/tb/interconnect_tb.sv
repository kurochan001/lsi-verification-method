`timescale 1ns/1ps
module interconnect_tb;
 parameter MUTATION=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0;
 reg [1:0] awvalid=0,wvalid=0,wlast=0,bready=0,arvalid=0,rready=0;
 reg [29:0] awaddr=0,araddr=0;reg [15:0] awlen=0,arlen=0;reg [3:0] awid=0,arid=0;
 reg [63:0] wdata=0;reg [7:0] wstrb=0;
 wire [1:0] awready,wready,bvalid,arready,rvalid,rlast;wire [3:0] bid,bresp,rid,rresp,grant_w,grant_r;wire [63:0] rdata;
 axi_interconnect #(.MUTATION(MUTATION)) dut(.*);
 integer v[0:27],fd,n,checks=0,writes=0,reads=0,write_beats=0,read_beats=0,errors=0;
 reg [1:0] aw_seen=0,ar_seen=0,active_w=0,active_r=0;
 reg [14:0] address_w[0:1],address_r[0:1];reg [1:0] priority_w=0,priority_r=0;
 integer route_w[0:1],route_r[0:1];reg [1:0] owner_w=0,owner_r=0;
 reg [1:0] b_hold=0,r_hold=0;reg [3:0] old_b[0:1];reg [36:0] old_r[0:1];
 string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"batch=%0d",checks);end endtask
 // Independent ledger from upstream handshakes and downstream interface observations.
 always @(posedge clk)if(rst_n)begin
  for(integer t=0;t<2;t=t+1)begin
   for(integer m=0;m<2;m=m+1)begin
    if(grant_w[2*t+m])begin
     if(!aw_seen[m] || address_w[m][13]!=t || address_w[m][14])fail("IC_ROUTE");
     if(aw_seen[0] && aw_seen[1] && !address_w[0][14] && !address_w[1][14] && address_w[0][13]==t && address_w[1][13]==t && m!=priority_w[t])fail("IC_FAIRNESS");
     owner_w[t]=m;route_w[t]=address_w[m];aw_seen[m]=0;
     $display("COVER route/write-target%0d",t);
    end
    if(grant_r[2*t+m])begin
     if(!ar_seen[m] || address_r[m][13]!=t || address_r[m][14])fail("IC_ROUTE");
     if(ar_seen[0] && ar_seen[1] && !address_r[0][14] && !address_r[1][14] && address_r[0][13]==t && address_r[1][13]==t && m!=priority_r[t])fail("IC_FAIRNESS");
     owner_r[t]=m;route_r[t]=address_r[m];ar_seen[m]=0;
     $display("COVER route/read-target%0d",t);
    end
   end
   if(dut.s_awvalid[t] && dut.s_awready[t] && dut.s_awaddr[t]!==route_w[t][12:0])fail("IC_ROUTE");
   if(dut.s_arvalid[t] && dut.s_arready[t] && dut.s_araddr[t]!==route_r[t][12:0])fail("IC_ROUTE");
   if(dut.s_bvalid[t] && dut.s_bready[t])priority_w[t]=!owner_w[t];
   if(dut.s_rvalid[t] && dut.s_rready[t] && dut.s_rlast[t])priority_r[t]=!owner_r[t];
  end
  for(integer m=0;m<2;m=m+1)begin
   if(awvalid[m] && awready[m])begin aw_seen[m]=1;active_w[m]=1;address_w[m]=awaddr[15*m+:15];end
   if(arvalid[m] && arready[m])begin ar_seen[m]=1;active_r[m]=1;address_r[m]=araddr[15*m+:15];end
   if(bvalid[m] && !active_w[m])fail("IC_RESPONSE");
   if(rvalid[m] && !active_r[m])fail("IC_RESPONSE");
   if(b_hold[m] && (!bvalid[m] || {bid[2*m+:2],bresp[2*m+:2]}!==old_b[m]))fail("IC_RESPONSE");
   if(r_hold[m] && (!rvalid[m] || {rid[2*m+:2],rresp[2*m+:2],rlast[m],rdata[32*m+:32]}!==old_r[m]))fail("IC_RESPONSE");
   b_hold[m]=bvalid[m]&&!bready[m];old_b[m]={bid[2*m+:2],bresp[2*m+:2]};
   r_hold[m]=rvalid[m]&&!rready[m];old_r[m]={rid[2*m+:2],rresp[2*m+:2],rlast[m],rdata[32*m+:32]};
   if(bvalid[m] && bready[m])begin active_w[m]=0;aw_seen[m]=0;end
   if(rvalid[m] && rready[m] && rlast[m])begin active_r[m]=0;ar_seen[m]=0;end
  end
  if((|grant_w) && (|grant_r))$display("COVER concurrency/read-write");
  if(aw_seen==3 && address_w[0][13]==address_w[1][13])$display("COVER arbitration/contention");
 end
 function [3:0] mask(input integer mode,input integer beat);
  begin case(mode)0:mask=15;1:mask=5;2:mask=0;default:mask=1<<(beat%4);endcase end
 endfunction
 task automatic transfer(input integer m);
  integer base,op,address,beats,ident,seed,mode,awd,wd,stall,error,tick,wb,rb,blocked;
  reg aw_done,ar_done,finished;
  begin
   base=14*m;op=v[base];address=v[base+1];beats=v[base+2];ident=v[base+3];seed=v[base+4];mode=v[base+5];
   awd=v[base+6];wd=v[base+7];stall=v[base+8];error=v[base+9];
   aw_done=0;ar_done=0;finished=op==0;wb=0;rb=0;blocked=0;tick=0;
   while(!finished && tick<600)begin
    awaddr[15*m+:15]=address;araddr[15*m+:15]=address;awlen[8*m+:8]=beats-1;arlen[8*m+:8]=beats-1;awid[2*m+:2]=ident;arid[2*m+:2]=ident;
    awvalid[m]=op==1 && !aw_done && tick>=awd;arvalid[m]=op==2 && !ar_done && tick>=awd;
    wvalid[m]=op==1 && wb<beats && tick>=wd;wdata[32*m+:32]=seed+32'h01030507*wb;wstrb[4*m+:4]=mask(mode,wb);wlast[m]=wb==beats-1;
    bready[m]=op==1 && blocked>=stall;rready[m]=op==2 && blocked>=stall;
    @(posedge clk);
    if(awvalid[m] && awready[m])aw_done=1;if(arvalid[m] && arready[m])ar_done=1;
    if(wvalid[m] && wready[m])begin wb=wb+1;write_beats=write_beats+1;end
    if(bvalid[m] && !bready[m] || rvalid[m] && !rready[m])blocked=blocked+1;
    if(bvalid[m] && bready[m])begin
     if(bid[2*m+:2]!==ident[1:0] || bresp[2*m+:2]!==error[1:0])fail("IC_RESPONSE");
     writes=writes+1;if(error)errors=errors+1;finished=1;
    end
    if(rvalid[m] && rready[m])begin
     if(rid[2*m+:2]!==ident[1:0] || rresp[2*m+:2]!==error[1:0] || rlast[m]!==(rb==beats-1))fail("IC_RESPONSE");
     if(rdata[32*m+:32]!==v[base+10+rb])fail("IC_DATA");
     rb=rb+1;read_beats=read_beats+1;blocked=0;
     if(rb==beats)begin reads=reads+1;if(error)errors=errors+1;finished=1;end
    end
    #1;@(negedge clk);tick=tick+1;
   end
   awvalid[m]=0;wvalid[m]=0;arvalid[m]=0;bready[m]=0;rready[m]=0;
   if(!finished)fail("IC_RESPONSE");
   if(op)begin
    $display("COVER master/%0d",m);if(error==3)$display("COVER response/decode-error");
    if(error==2)$display("COVER response/slave-error");if(stall)$display("COVER response/backpressure");
    if(beats>1)$display("COVER burst/multiple");
   end
  end
 endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,interconnect_tb);repeat(3)@(negedge clk);rst_n=1;
  fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");
  while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18],v[19],v[20],v[21],v[22],v[23],v[24],v[25],v[26],v[27]);
   if(n!=28)$fatal(1,"bad row");
   fork transfer(0);transfer(1);join
   repeat(2)@(negedge clk);checks=checks+1;
  end
  $display("COUNT writes=%0d",writes);$display("COUNT reads=%0d",reads);$display("COUNT write_beats=%0d",write_beats);$display("COUNT read_beats=%0d",read_beats);$display("COUNT errors=%0d",errors);
  $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
