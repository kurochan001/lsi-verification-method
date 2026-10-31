module contract_formal #(parameter ROLE=3,MUTATION=0,ASSUME_HOLD=1,LOCK_RESET=0);
  (* gclk *)reg clk;
  (* anyseq *)reg rst_n,issue,external_valid,external_ready;
  (* anyseq *)reg [7:0] value,external_data;
  reg past_valid=0;reg toggle=0;
  wire valid,ready,done;wire [7:0] data,result;
  generate
    if(ROLE==0)begin
      request_source #(.MUTATION(MUTATION)) src(clk,rst_n,issue,value,external_ready,valid,data);
      assign ready=external_ready;assign done=0;assign result=0;
    end else if(ROLE==1)begin
      assign valid=external_valid;assign data=external_data;
      request_sink #(.MUTATION(MUTATION)) dst(clk,rst_n,valid,data,ready,done,result);
    end else begin
      wire source_valid;wire [7:0] source_data;
      request_source #(.MUTATION(MUTATION)) src(clk,rst_n,issue,value,ready,source_valid,source_data);
      assign valid=source_valid;
      assign data=source_data^((MUTATION==3 && !ready && toggle) ? 8'h01:8'h00);
      request_sink #(.MUTATION(MUTATION)) dst(clk,rst_n,valid,data,ready,done,result);
    end
  endgenerate
  always @(posedge clk)begin
    past_valid<=1;toggle<=!toggle;
    if(!past_valid)as_initial_reset:assume(!rst_n);
    if(past_valid && !$past(rst_n))ap_reset:assert(ROLE==0 ? !valid:!done);
    cp_activity:cover(rst_n && (ROLE==0 ? valid && ready:done));
    cp_stall:cover(rst_n && valid && !ready);
  end
  generate
    if(LOCK_RESET)always @(posedge clk)as_lock_reset:assume(!rst_n);
    if(ROLE==1 && ASSUME_HOLD)always @(posedge clk)
      if(past_valid && rst_n && $past(rst_n && valid && !ready))as_upstream_hold:assume(valid && data==$past(data));
    if(ROLE==0)always @(posedge clk)
      if(past_valid && rst_n && $past(rst_n && valid && !ready))ap_hold:assert(valid && data==$past(data));
    if(ROLE==2)always @(posedge clk)
      if(past_valid && rst_n && $past(rst_n && valid && !ready))ap_contract:assert(valid && data==$past(data));
    if(ROLE==1 || ROLE==3)always @(posedge clk)begin
      if(past_valid && rst_n && $past(rst_n))begin
        ap_done:assert(done==$past(valid && ready));
        if(done)ap_result:assert(result==($past(data)^8'ha5));
      end
    end
  endgenerate
endmodule
