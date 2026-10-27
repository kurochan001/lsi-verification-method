// Two masters, two AXI4 RAM targets. One outstanding request per master/direction.
module axi_interconnect #(parameter MUTATION=0)(
 input wire clk,rst_n,
 input wire [1:0] awvalid,wvalid,wlast,bready,arvalid,rready,
 input wire [29:0] awaddr,araddr,input wire [15:0] awlen,arlen,input wire [3:0] awid,arid,
 input wire [63:0] wdata,input wire [7:0] wstrb,
 output reg [1:0] awready,wready,bvalid,arready,rvalid,rlast,
 output reg [3:0] bid,bresp,rid,rresp,output reg [63:0] rdata,
 output reg [3:0] grant_w,grant_r
);
 reg [1:0] wfull,rfull,wbusy,rbusy,wb_dec,rd_dec,wd_dec;
 reg [14:0] wa[0:1],ra[0:1];reg [7:0] wl[0:1],rl[0:1],wbcount[0:1],rbcount[0:1];
 reg [1:0] wi[0:1],ri[0:1];
 reg [1:0] active_w,active_r,sent_w,sent_r,owner_w,owner_r,rr_w,rr_r;
 wire [1:0] s_awready,s_wready,s_bvalid,s_arready,s_rvalid,s_rlast;
 wire [1:0] s_bid[0:1],s_bresp[0:1],s_rid[0:1],s_rresp[0:1];wire [31:0] s_rdata[0:1];
 reg [1:0] s_awvalid,s_wvalid,s_wlast,s_bready,s_arvalid,s_rready;
 reg [12:0] s_awaddr[0:1],s_araddr[0:1];reg [7:0] s_awlen[0:1],s_arlen[0:1];
 reg [1:0] s_awid[0:1],s_arid[0:1];reg [31:0] s_wdata[0:1];reg [3:0] s_wstrb[0:1];
 integer m,t,ow,orr;reg [1:0] eligible_w,eligible_r;integer chosen_w[0:1],chosen_r[0:1];
 genvar g;generate for(g=0;g<2;g=g+1)begin: targets
  axi4_ram ram(.clk(clk),.rst_n(rst_n),.awvalid(s_awvalid[g]),.awaddr(s_awaddr[g]),.awlen(s_awlen[g]),.awsize(3'd2),.awburst(2'd1),.awid(s_awid[g]),.awready(s_awready[g]),
    .wvalid(s_wvalid[g]),.wdata(s_wdata[g]),.wstrb(s_wstrb[g]),.wlast(s_wlast[g]),.wready(s_wready[g]),
    .bvalid(s_bvalid[g]),.bready(s_bready[g]),.bid(s_bid[g]),.bresp(s_bresp[g]),
    .arvalid(s_arvalid[g]),.araddr(s_araddr[g]),.arlen(s_arlen[g]),.arsize(3'd2),.arburst(2'd1),.arid(s_arid[g]),.arready(s_arready[g]),
    .rvalid(s_rvalid[g]),.rready(s_rready[g]),.rdata(s_rdata[g]),.rid(s_rid[g]),.rresp(s_rresp[g]),.rlast(s_rlast[g]));
 end endgenerate
 always @* begin
  awready=0;wready=0;bvalid=0;bid=0;bresp=0;arready=0;rvalid=0;rid=0;rresp=0;rdata=0;rlast=0;grant_w=0;grant_r=0;
  s_awvalid=0;s_wvalid=0;s_wlast=0;s_bready=0;s_arvalid=0;s_rready=0;
  for(m=0;m<2;m=m+1)begin
   awready[m]=rst_n && !wfull[m] && !wbusy[m];arready[m]=rst_n && !rfull[m] && !rbusy[m];
   if(wd_dec[m])wready[m]=rst_n;
   if(wb_dec[m])begin bvalid[m]=rst_n;bid[2*m+:2]=wi[m];bresp[2*m+:2]=3;end
   if(rd_dec[m])begin rvalid[m]=rst_n;rid[2*m+:2]=ri[m];rresp[2*m+:2]=3;rlast[m]=rbcount[m]==rl[m];end
  end
  for(t=0;t<2;t=t+1)begin
   eligible_w=0;eligible_r=0;
   for(m=0;m<2;m=m+1)begin
    eligible_w[m]=wfull[m] && !wa[m][14] && ((wa[m][13] ^ (MUTATION==2))==t);
    eligible_r[m]=rfull[m] && !ra[m][14] && ((ra[m][13] ^ (MUTATION==2))==t);
   end
   chosen_w[t]=eligible_w[rr_w[t]] && MUTATION!=3 ? rr_w[t] : eligible_w[0] ? 0 : 1;
   chosen_r[t]=eligible_r[rr_r[t]] && MUTATION!=3 ? rr_r[t] : eligible_r[0] ? 0 : 1;
   if(rst_n && !active_w[t] && |eligible_w)grant_w[2*t+chosen_w[t]]=1;
   if(rst_n && !active_r[t] && |eligible_r)grant_r[2*t+chosen_r[t]]=1;
   ow=owner_w[t];orr=owner_r[t];
   s_awaddr[t]=wa[ow][12:0];s_awlen[t]=wl[ow];s_awid[t]=wi[ow];
   s_araddr[t]=ra[orr][12:0];s_arlen[t]=rl[orr];s_arid[t]=ri[orr];
   s_wdata[t]=wdata[32*ow+:32] ^ (MUTATION==4 ? 32'b1:0);s_wstrb[t]=wstrb[4*ow+:4];s_wlast[t]=wlast[ow];
   if(active_w[t])begin
    s_awvalid[t]=!sent_w[t];s_wvalid[t]=wvalid[ow];wready[ow]=s_wready[t];
    bvalid[ow ^ (MUTATION==1)]=s_bvalid[t];bid[2*(ow ^ (MUTATION==1))+:2]=s_bid[t];bresp[2*(ow ^ (MUTATION==1))+:2]=s_bresp[t];s_bready[t]=bready[ow];
   end
   if(active_r[t])begin
    s_arvalid[t]=!sent_r[t];rvalid[orr]=s_rvalid[t];rid[2*orr+:2]=s_rid[t];rresp[2*orr+:2]=s_rresp[t];
    rdata[32*orr+:32]=s_rdata[t];rlast[orr]=s_rlast[t];s_rready[t]=rready[orr];
   end
  end
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   wfull<=0;rfull<=0;wbusy<=0;rbusy<=0;active_w<=0;active_r<=0;sent_w<=0;sent_r<=0;owner_w<=0;owner_r<=0;rr_w<=0;rr_r<=0;wb_dec<=0;rd_dec<=0;wd_dec<=0;
   for(integer i=0;i<2;i=i+1)begin wa[i]<=0;ra[i]<=0;wl[i]<=0;rl[i]<=0;wi[i]<=0;ri[i]<=0;wbcount[i]<=0;rbcount[i]<=0;end
  end else begin
   for(integer i=0;i<2;i=i+1)begin
    if(awvalid[i] && awready[i])begin wfull[i]<=1;wa[i]<=awaddr[15*i+:15];wl[i]<=awlen[8*i+:8];wi[i]<=awid[2*i+:2];end
    if(arvalid[i] && arready[i])begin rfull[i]<=1;ra[i]<=araddr[15*i+:15];rl[i]<=arlen[8*i+:8];ri[i]<=arid[2*i+:2];end
    if(wfull[i] && wa[i][14])begin wfull[i]<=0;wbusy[i]<=1;wd_dec[i]<=1;wbcount[i]<=0;end
    if(rfull[i] && ra[i][14])begin rfull[i]<=0;rbusy[i]<=1;rd_dec[i]<=1;rbcount[i]<=0;end
    if(wd_dec[i] && wvalid[i] && wready[i])begin
     if(wbcount[i]==wl[i])begin wd_dec[i]<=0;wb_dec[i]<=1;end else wbcount[i]<=wbcount[i]+1'b1;
    end
    if(wb_dec[i] && bready[i])begin wb_dec[i]<=0;wbusy[i]<=0;end
    if(rd_dec[i] && rready[i])begin
     if(rbcount[i]==rl[i])begin rd_dec[i]<=0;rbusy[i]<=0;end else rbcount[i]<=rbcount[i]+1'b1;
    end
   end
   for(integer i=0;i<2;i=i+1)begin
    if(grant_w[2*i] || grant_w[2*i+1])begin active_w[i]<=1;owner_w[i]<=chosen_w[i];sent_w[i]<=0;wfull[chosen_w[i]]<=0;wbusy[chosen_w[i]]<=1;end
    if(grant_r[2*i] || grant_r[2*i+1])begin active_r[i]<=1;owner_r[i]<=chosen_r[i];sent_r[i]<=0;rfull[chosen_r[i]]<=0;rbusy[chosen_r[i]]<=1;end
    if(s_awvalid[i] && s_awready[i])sent_w[i]<=1;
    if(s_arvalid[i] && s_arready[i])sent_r[i]<=1;
    if(active_w[i] && s_bvalid[i] && s_bready[i])begin active_w[i]<=0;wbusy[owner_w[i]]<=0;rr_w[i]<=!owner_w[i];end
    if(active_r[i] && s_rvalid[i] && s_rready[i] && s_rlast[i])begin active_r[i]<=0;rbusy[owner_r[i]]<=0;rr_r[i]<=!owner_r[i];end
   end
  end
 end
endmodule
