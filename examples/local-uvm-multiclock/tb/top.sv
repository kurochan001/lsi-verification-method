`timescale 1ps/1ps
`include "uvm_macros.svh"
module top;
  import uvm_pkg::*;import uvm_apb_pkg::fatal_to_exit;import mc_pkg::*;
  bit src_clk=0,dst_clk=0;int pair_id,mutation,sva_off,sva_fault;int src_count,dst_count;bit [7:0] tick;bit traffic_seen,reset_after_traffic;
  mc_if bus(src_clk,dst_clk);
  wire [6:0] ready,valid,src_up,dst_up;wire [7:0] data[7];wire [15:0] ids[7];
  for(genvar m=0;m<7;m++)begin: variants
    reset_mailbox #(.MUTATION(m)) dut(src_clk,dst_clk,bus.src_rst_n,bus.dst_rst_n,bus.src_valid,bus.src_data,bus.src_id,
      ready[m],src_up[m],dst_up[m],bus.dst_ready,valid[m],data[m],ids[m]);
  end
  assign bus.src_ready=ready[mutation];assign bus.src_up=src_up[mutation];assign bus.dst_up=dst_up[mutation];
  assign bus.dst_valid=valid[mutation];assign bus.dst_data=data[mutation];assign bus.dst_id=ids[mutation];
  wire [7:0] checked_data=bus.dst_data^((sva_fault!=0 && bus.dst_valid && !bus.dst_ready) ? tick:8'b0);
  initial begin void'($value$plusargs("CLOCK_PAIR=%d",pair_id));forever #((pair_id==0 ? 3:pair_id==1 ? 5:2)*1000)src_clk=!src_clk;end
  initial begin void'($value$plusargs("CLOCK_PAIR=%d",pair_id));if(pair_id==1)#1000;forever #((pair_id==0 ? 5:pair_id==1 ? 3:15)*1000)dst_clk=!dst_clk;end
  always @(posedge src_clk or negedge bus.src_rst_n)begin
    if(!bus.src_rst_n)src_count=0;
    else begin
      if(sva_off==0)ap_src_release:assert(bus.src_up==(src_count>=2))else begin $display("CHECK_FAIL MC_RELEASE");$fatal(1,"source reset release differs");end
      if(src_count<2)src_count++;
    end
  end
  always @(posedge dst_clk or negedge bus.dst_rst_n)begin
    if(!bus.dst_rst_n)dst_count=0;
    else begin
      if(sva_off==0)ap_dst_release:assert(bus.dst_up==(dst_count>=2))else begin $display("CHECK_FAIL MC_RELEASE");$fatal(1,"destination reset release differs");end
      if(dst_count<2)dst_count++;
    end
  end
  // Release contract at the source port, independent of the RTL's synchronizers: after a channel
  // reset the sender needs two local edges, and then dst_up must be sampled on two further edges.
  wire channel_rst_n=bus.src_rst_n && bus.dst_rst_n;
  int channel_count,peer_count;
  always @(posedge src_clk or negedge channel_rst_n)begin
    if(!channel_rst_n)begin channel_count=0;peer_count=0;end
    else begin
      if(sva_off==0)ap_channel_release:assert(!bus.src_ready || (channel_count>=2 && peer_count>=2))else begin $display("CHECK_FAIL MC_CHANNEL");$fatal(1,"source became ready before the channel release completed");end
      if(channel_count>=2 && bus.dst_up && peer_count<2)peer_count++;
      if(channel_count<2)channel_count++;
    end
  end
  // Release contract at the destination port: a request accepted after a channel reset needs two
  // local edges for the channel release, two synchronizer edges and a capture edge. Only a much
  // faster source has the request ready this early. A stale response is left to the scoreboard.
  int receiver_count;bit accepted_after_release;bit [15:0] accepted_id;
  always @(posedge src_clk or negedge channel_rst_n)
    if(!channel_rst_n)accepted_after_release<=0;
    else if(bus.src_valid && bus.src_ready)begin accepted_after_release<=1;accepted_id<=bus.src_id;end
  always @(posedge dst_clk or negedge channel_rst_n)begin
    if(!channel_rst_n)receiver_count=0;
    else begin
      if(sva_off==0)ap_receiver_release:assert(!(bus.dst_valid && accepted_after_release && bus.dst_id==accepted_id) || receiver_count>=5)else begin $display("CHECK_FAIL MC_CHANNEL");$fatal(1,"destination became valid before the channel release completed");end
      if(receiver_count<5)receiver_count++;
    end
  end
  always @(posedge dst_clk)tick<=tick+1;
  always @(posedge src_clk)if(bus.src_valid && bus.src_ready)traffic_seen<=1;
  always @(negedge bus.src_rst_n or negedge bus.dst_rst_n)if(traffic_seen)reset_after_traffic<=1;
  // With a slow destination clock a short reset can fall entirely between two of its edges.
  bit reset_since_dst_edge;
  always @(posedge dst_clk or negedge channel_rst_n)
    if(!channel_rst_n)reset_since_dst_edge<=1;else reset_since_dst_edge<=0;
  ap_hold:assert property(@(posedge dst_clk) disable iff(!bus.src_rst_n || !bus.dst_rst_n || reset_since_dst_edge || sva_off!=0)
    (bus.dst_valid && !bus.dst_ready)|=>(bus.dst_valid && $stable({checked_data,bus.dst_id})))
    else begin $display("CHECK_FAIL MC_DST_HOLD");$fatal(1,"destination changed while stalled");end
  cp_source:cover property(@(posedge src_clk) sva_off==0 && bus.src_valid && bus.src_ready)$display("MC_COVER cp_source");
  cp_destination:cover property(@(posedge dst_clk) sva_off==0 && bus.dst_valid && bus.dst_ready)$display("MC_COVER cp_destination");
  cp_stall:cover property(@(posedge dst_clk) sva_off==0 && bus.dst_valid && !bus.dst_ready)$display("MC_COVER cp_stall");
  cp_src_reset:cover property(@(posedge src_clk) sva_off==0 && !bus.src_rst_n && bus.dst_rst_n)$display("MC_COVER cp_src_reset");
  cp_dst_reset:cover property(@(posedge dst_clk) sva_off==0 && bus.src_rst_n && !bus.dst_rst_n)$display("MC_COVER cp_dst_reset");
  cp_both_reset:cover property(@(posedge src_clk) sva_off==0 && !bus.src_rst_n && !bus.dst_rst_n)$display("MC_COVER cp_both_reset");
  cp_src_up:cover property(@(posedge src_clk) sva_off==0 && bus.src_up && src_count==2)$display("MC_COVER cp_src_up");
  cp_dst_up:cover property(@(posedge dst_clk) sva_off==0 && bus.dst_up && dst_count==2)$display("MC_COVER cp_dst_up");
  cp_recovery:cover property(@(posedge dst_clk) sva_off==0 && bus.dst_valid && bus.dst_ready && reset_after_traffic)$display("MC_COVER cp_recovery");
  cp_release_wait:cover property(@(posedge src_clk) sva_off==0 && channel_rst_n && bus.src_valid && !bus.src_ready && !(channel_count>=2 && peer_count>=2))$display("MC_COVER cp_release_wait");
  initial begin
    string wave;fatal_to_exit catcher;
    bus.src_rst_n=0;bus.dst_rst_n=0;bus.src_valid=0;bus.src_data=0;bus.src_id=0;bus.dst_ready=0;
    void'($value$plusargs("MUTATION=%d",mutation));void'($value$plusargs("SVA_OFF=%d",sva_off));void'($value$plusargs("SVA_FAULT=%d",sva_fault));
    if(mutation<0 || mutation>6 || !$value$plusargs("WAVE=%s",wave))$fatal(1,"invalid run arguments");
    $dumpfile(wave);$dumpvars(0,top);catcher=new;uvm_report_cb::add(null,catcher);
    uvm_config_db#(virtual mc_if)::set(null,"uvm_test_top.env","vif",bus);run_test("mc_test");
  end
  initial begin #100000000;$fatal(1,"multiclock watchdog");end
endmodule
