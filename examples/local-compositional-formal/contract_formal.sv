// Connection between the two blocks. MUTATION 3 and 5 are deliberate wiring faults.
module request_wiring #(parameter MUTATION=0)(
  input wire source_valid,input wire [7:0] source_data,input wire ready,toggle,
  output wire valid,output wire [7:0] data,output wire source_ready
);
  assign valid=source_valid && !(MUTATION==5 && !ready && toggle);
  assign data=source_data^((MUTATION==3 && !ready && toggle) ? 8'h01:8'h00);
  assign source_ready=ready;
endmodule

module contract_formal #(parameter ROLE=3,MUTATION=0,ASSUME_HOLD=1,LOCK_RESET=0);
  (* gclk *)reg clk;
  (* anyseq *)reg rst_n,issue,external_valid,external_ready;
  (* anyseq *)reg [7:0] value,external_data;
  reg past_valid=0;reg toggle=0;
  wire source_valid,source_ready;wire [7:0] source_data;
  wire valid,ready,done;wire [7:0] data,result;
  generate
    if(ROLE==0)begin
      request_source #(.MUTATION(MUTATION)) src(clk,rst_n,issue,value,source_ready,source_valid,source_data);
      assign source_ready=external_ready;assign ready=external_ready;
      assign valid=source_valid;assign data=source_data;assign done=0;assign result=0;
    end else if(ROLE==1)begin
      assign valid=external_valid;assign data=external_data;
      assign source_valid=0;assign source_data=0;assign source_ready=0;
      request_sink #(.MUTATION(MUTATION)) dst(clk,rst_n,valid,data,ready,done,result);
    end else if(ROLE==2)begin
      // Wiring only: both blocks are replaced by free signals constrained by their contracts.
      assign source_valid=external_valid;assign source_data=external_data;assign ready=external_ready;
      request_wiring #(.MUTATION(MUTATION)) link(source_valid,source_data,ready,toggle,valid,data,source_ready);
      assign done=0;assign result=0;
    end else begin
      request_source #(.MUTATION(MUTATION)) src(clk,rst_n,issue,value,source_ready,source_valid,source_data);
      request_wiring #(.MUTATION(MUTATION)) link(source_valid,source_data,ready,toggle,valid,data,source_ready);
      request_sink #(.MUTATION(MUTATION)) dst(clk,rst_n,valid,data,ready,done,result);
    end
  endgenerate
  always @(posedge clk)begin
    past_valid<=1;toggle<=!toggle;
    if(!past_valid)as_initial_reset:assume(!rst_n);
    cp_activity:cover(rst_n && (ROLE==1 || ROLE==3 ? done:valid && ready));
    cp_stall:cover(rst_n && valid && !ready);
    cp_hold:cover(past_valid && rst_n && $past(rst_n && valid && !ready));
    cp_nonzero:cover(rst_n && (ROLE==1 || ROLE==3 ? done && result!=8'ha5:valid && !ready && data!=0));
  end
  generate
    if(LOCK_RESET)always @(posedge clk)as_lock_reset:assume(!rst_n);
    if(ROLE!=2)always @(posedge clk)
      if(past_valid && !$past(rst_n))ap_reset:assert(ROLE==0 ? !valid:!done);
    // The hold contract has one statement per interface. As written it is the producer's guarantee
    // and the consumer's assumption; formal_tasks.prepare flips these same two statements for the
    // connection proof, so an assumption and the guarantee that discharges it cannot drift apart.
    if(ROLE==0 || ROLE==2 && ASSUME_HOLD)always @(posedge clk)
      if(past_valid && rst_n && $past(rst_n && source_valid && !source_ready))ag_source_hold:assert(source_valid && source_data==$past(source_data));
    if(ROLE==1 && ASSUME_HOLD || ROLE==2)always @(posedge clk)
      if(past_valid && rst_n && $past(rst_n && valid && !ready))ag_sink_hold:assume(valid && data==$past(data));
    if(ROLE==1 || ROLE==3)always @(posedge clk)begin
      if(past_valid && rst_n && $past(rst_n))begin
        ap_done:assert(done==$past(valid && ready));
        if(done)ap_result:assert(result==($past(data)^8'ha5));
      end
    end
  endgenerate
endmodule
