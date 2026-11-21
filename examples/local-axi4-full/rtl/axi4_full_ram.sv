// Educational AXI4 memory target for the features the local-axi4 subset leaves out:
// FIXED/INCR/WRAP bursts, narrow and unaligned transfers, exclusive access and 256-beat bursts.
// One write and one read transaction are in flight at a time. Not a compliant or production design.
module axi4_full_ram #(parameter MUTATION=0)(
 input wire clk,rst_n,
 input wire awvalid,input wire [12:0] awaddr,input wire [7:0] awlen,input wire [2:0] awsize,
 input wire [1:0] awburst,awid,input wire awlock,output wire awready,
 input wire wvalid,input wire [31:0] wdata,input wire [3:0] wstrb,input wire wlast,output wire wready,
 output wire bvalid,input wire bready,output wire [1:0] bid,bresp,
 input wire arvalid,input wire [12:0] araddr,input wire [7:0] arlen,input wire [2:0] arsize,
 input wire [1:0] arburst,arid,input wire arlock,output wire arready,
 output wire rvalid,input wire rready,output wire [31:0] rdata,output wire [1:0] rid,rresp,output wire rlast
);
 localparam [1:0] FIXED=2'd0,INCR=2'd1,WRAP=2'd2;
 localparam [1:0] W_IDLE=2'd0,W_DATA=2'd1,W_RESP=2'd2;
 reg [7:0] memory[0:8191];
 // One exclusive reservation per ID: the request that made it and the byte range it covers.
 reg res_valid[0:3];
 reg [12:0] res_addr[0:3],res_lo[0:3],res_hi[0:3];
 reg [7:0] res_len[0:3];
 reg [2:0] res_size[0:3];
 reg [1:0] res_burst[0:3];
 reg [1:0] w_state,w_burst,w_id;
 reg [12:0] w_addr,w_lo,w_hi;
 reg [7:0] w_len,w_cnt;
 reg [1:0] w_size;
 reg w_do,w_err,w_ex;
 reg r_state,r_err,r_ex;
 reg [12:0] r_addr,r_lo,r_hi;
 reg [7:0] r_len,r_cnt;
 reg [1:0] r_size,r_burst,r_id;
 reg [31:0] r_data;
 integer i,j;

 // Start of the size-aligned container that holds an address.
 function automatic [12:0] align(input [12:0] a,input [1:0] size);
   case(size) 2'd0:align=a;2'd1:align={a[12:1],1'b0};default:align={a[12:2],2'b00};endcase
 endfunction
 // Bytes of the whole burst when every beat is one container wide.
 function automatic [12:0] span(input [7:0] len,input [1:0] size);
   span=({5'd0,len}+13'd1)<<size;
 endfunction
 function automatic illegal(input [12:0] a,input [7:0] len,input [2:0] size,input [1:0] burst);
   reg [12:0] base,last_in_page;
   begin
     base=align(a,size[1:0]);
     last_in_page={1'b0,base[11:0]}+span(len,size[1:0])-13'd1;
     illegal=size>3'd2 || burst==2'd3 ||
             (burst==WRAP && (!(len==8'd1 || len==8'd3 || len==8'd7 || len==8'd15) || base!=a)) ||
             (burst==FIXED && len>8'd15) ||
             (burst==INCR && MUTATION!=6 && last_in_page>13'd4095);
   end
 endfunction
 // First and last byte a legal burst can touch.
 function automatic [12:0] range_lo(input [12:0] a,input [7:0] len,input [1:0] size,input [1:0] burst);
   reg [12:0] total;
   begin total=span(len,size);range_lo=burst==WRAP ? (a & ~(total-13'd1)):a;end
 endfunction
 function automatic [12:0] range_hi(input [12:0] a,input [7:0] len,input [1:0] size,input [1:0] burst);
   reg [12:0] total;
   begin
     total=span(len,size);
     case(burst)
       WRAP:range_hi=(a & ~(total-13'd1))+total-13'd1;
       FIXED:range_hi=align(a,size)+(13'd1<<size)-13'd1;
       default:range_hi=align(a,size)+total-13'd1;
     endcase
   end
 endfunction
 // Address of the beat after the one at a.
 function automatic [12:0] step(input [12:0] a,input [1:0] size,input [1:0] burst,input [12:0] hi,input [12:0] lo);
   reg [13:0] n;
   begin
     n={1'b0,align(a,size)}+((MUTATION==7 && burst==INCR) ? 14'd4:(14'd1<<size));
     if(burst==FIXED)step=MUTATION==2 ? n[12:0]:a;
     else if(burst==WRAP && n>{1'b0,hi} && MUTATION!=1)step=lo;
     else step=n[12:0];
   end
 endfunction
 // Byte lanes a beat at address a carries: from the address up to the end of its container.
 function automatic [3:0] lanes(input [1:0] offset,input [1:0] size,input whole);
   reg [1:0] lo,hi;
   begin
     case(size) 2'd0:begin lo=offset;hi=offset;end
                2'd1:begin lo=whole ? {offset[1],1'b0}:offset;hi={offset[1],1'b1};end
                default:begin lo=whole ? 2'd0:offset;hi=2'd3;end
     endcase
     lanes={hi==2'd3,lo<=2'd2 && hi>=2'd2,lo<=2'd1 && hi>=2'd1,lo==2'd0};
   end
 endfunction
 function automatic [31:0] fetch(input [12:0] a,input [1:0] size);
   reg [3:0] m;
   begin
     m=lanes(a[1:0],size,MUTATION==3);
     fetch={m[3] ? memory[{a[12:2],2'd3}]:8'd0,m[2] ? memory[{a[12:2],2'd2}]:8'd0,
            m[1] ? memory[{a[12:2],2'd1}]:8'd0,m[0] ? memory[{a[12:2],2'd0}]:8'd0};
   end
 endfunction

 wire aw_ill=illegal(awaddr,awlen,awsize,awburst);
 wire aw_match=res_valid[awid] && res_addr[awid]==awaddr && res_len[awid]==awlen &&
               res_size[awid]==awsize && res_burst[awid]==awburst;
 wire [3:0] w_lanes=lanes(w_addr[1:0],w_size,1'b0);
 wire w_final=w_cnt==w_len;
 wire ar_ill=illegal(araddr,arlen,arsize,arburst);
 wire [12:0] ar_total=span(arlen,arsize[1:0]);
 // A reservation needs at most 16 beats, a power-of-two byte count and a start aligned to that count.
 wire ar_shape=arlen<=8'd15 && (ar_total & (ar_total-13'd1))==13'd0 && (araddr & (ar_total-13'd1))==13'd0;
 wire [12:0] r_next=step(r_addr,r_size,r_burst,r_hi,r_lo);
 assign awready=w_state==W_IDLE;
 assign wready=w_state==W_DATA;
 assign bvalid=w_state==W_RESP;
 assign bid=w_id;
 assign bresp=w_err ? 2'b10:w_ex ? 2'b01:2'b00;
 assign arready=!r_state;
 assign rvalid=r_state;
 assign rdata=r_data;
 assign rid=r_id;
 assign rresp=r_err ? 2'b10:r_ex ? 2'b01:2'b00;
 assign rlast=MUTATION==5 ? r_cnt[6:0]==r_len[6:0]:r_cnt==r_len;

 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
     w_state<=W_IDLE;w_burst<=0;w_id<=0;w_addr<=0;w_lo<=0;w_hi<=0;w_len<=0;w_cnt<=0;w_size<=0;w_do<=0;w_err<=0;w_ex<=0;
     r_state<=0;r_err<=0;r_ex<=0;r_addr<=0;r_lo<=0;r_hi<=0;r_len<=0;r_cnt<=0;r_size<=0;r_burst<=0;r_id<=0;r_data<=0;
     for(i=0;i<4;i=i+1) begin
       res_valid[i]<=1'b0;res_addr[i]<=0;res_lo[i]<=0;res_hi[i]<=0;res_len[i]<=0;res_size[i]<=0;res_burst[i]<=0;
     end
     for(j=0;j<8192;j=j+1)memory[j]<=8'd0;
   end else begin
     // The read channel comes first, so that a write finishing in the same cycle still clears a reservation.
     if(!r_state) begin
       if(arvalid) begin
         r_state<=1'b1;r_addr<=araddr;r_len<=arlen;r_cnt<=8'd0;r_size<=arsize[1:0];r_burst<=arburst;r_id<=arid;
         r_lo<=range_lo(araddr,arlen,arsize[1:0],arburst);r_hi<=range_hi(araddr,arlen,arsize[1:0],arburst);
         r_err<=ar_ill;r_ex<=!ar_ill && arlock && ar_shape;
         r_data<=ar_ill ? 32'd0:fetch(araddr,arsize[1:0]);
         if(arlock) begin
           res_valid[arid]<=!ar_ill && ar_shape;
           res_addr[arid]<=araddr;res_len[arid]<=arlen;res_size[arid]<=arsize;res_burst[arid]<=arburst;
           res_lo[arid]<=range_lo(araddr,arlen,arsize[1:0],arburst);res_hi[arid]<=range_hi(araddr,arlen,arsize[1:0],arburst);
         end
       end
     end else if(rready) begin
       if(rlast)r_state<=1'b0;
       else begin r_cnt<=r_cnt+8'd1;r_addr<=r_next;r_data<=r_err ? 32'd0:fetch(r_next,r_size);end
     end
     case(w_state)
       W_IDLE:if(awvalid) begin
         w_state<=W_DATA;w_addr<=awaddr;w_len<=awlen;w_cnt<=8'd0;w_size<=awsize[1:0];w_burst<=awburst;w_id<=awid;
         w_lo<=range_lo(awaddr,awlen,awsize[1:0],awburst);w_hi<=range_hi(awaddr,awlen,awsize[1:0],awburst);
         w_err<=aw_ill;w_do<=!aw_ill && (!awlock || aw_match);w_ex<=!aw_ill && awlock && aw_match;
         // An exclusive write uses up the reservation of its ID whether it succeeds or not.
         if(awlock)res_valid[awid]<=1'b0;
       end
       W_DATA:if(wvalid) begin
         if(w_do) begin
           if(w_lanes[0] && wstrb[0])memory[{w_addr[12:2],2'd0}]<=wdata[7:0];
           if(w_lanes[1] && wstrb[1])memory[{w_addr[12:2],2'd1}]<=wdata[15:8];
           if(w_lanes[2] && wstrb[2])memory[{w_addr[12:2],2'd2}]<=wdata[23:16];
           if(w_lanes[3] && wstrb[3])memory[{w_addr[12:2],2'd3}]<=wdata[31:24];
         end
         if(wlast!=w_final)w_err<=1'b1;
         if(w_final) begin
           w_state<=W_RESP;
           // A write that was carried out ends every reservation whose bytes it could have changed.
           if(w_do && MUTATION!=4)
             for(i=0;i<4;i=i+1)if(res_valid[i] && res_lo[i]<=w_hi && w_lo<=res_hi[i])res_valid[i]<=1'b0;
         end else begin
           w_cnt<=w_cnt+8'd1;w_addr<=step(w_addr,w_size,w_burst,w_hi,w_lo);
         end
       end
       W_RESP:if(bready)w_state<=W_IDLE;
       default:w_state<=W_IDLE;
     endcase
   end
 end
endmodule
