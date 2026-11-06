`timescale 1ps/1ps
`include "uvm_macros.svh"
package mc_pkg;
  import uvm_pkg::*;import uvm_apb_pkg::fatal_to_exit;
  class mc_control extends uvm_object;
    `uvm_object_utils(mc_control)
    bit force_stall,stop_sink;
    function new(string name="mc_control");super.new(name);endfunction
  endclass
  class mc_config extends uvm_object;
    `uvm_object_utils(mc_config)
    virtual mc_if vif;mc_control control;int role;
    function new(string name="mc_config");super.new(name);endfunction
  endclass
  class mc_item extends uvm_sequence_item;
    `uvm_object_utils(mc_item)
    bit [7:0] data;bit [15:0] id;bit ready,src_reset_n,dst_reset_n,accepted;int align;
    function new(string name="mc_item");super.new(name);endfunction
  endclass
  class mc_driver extends uvm_driver#(mc_item);
    `uvm_component_utils(mc_driver)
    mc_config cfg;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    task run_phase(uvm_phase phase);
      forever begin
        mc_item t;seq_item_port.get_next_item(t);
        case(cfg.role)
          0:begin
            int cycles=0;
            @(negedge cfg.vif.src_clk);
            cfg.vif.src_valid=1;cfg.vif.src_data=t.data;cfg.vif.src_id=t.id;
            forever begin
              @(posedge cfg.vif.src_clk);
              if(!cfg.vif.src_rst_n || !cfg.vif.dst_rst_n)break;
              if(cfg.vif.src_ready)begin t.accepted=1;break;end
              cycles++;if(cycles>1000)`uvm_fatal("MC_DRIVER","source handshake did not complete")
            end
            @(negedge cfg.vif.src_clk);cfg.vif.src_valid=0;#1000;
          end
          1:begin
            @(negedge cfg.vif.dst_clk);cfg.vif.dst_ready=cfg.control.force_stall ? 0:t.ready;
            @(posedge cfg.vif.dst_clk);#1000;
          end
          2:begin
            // All clock edges are at integer nanoseconds; reset edges are half a
            // nanosecond later, so reset/clock scheduling races are excluded.
            // align places the reset right after the next destination or source handshake.
            case(t.align)
              1:do @(posedge cfg.vif.dst_clk);while(!(cfg.vif.dst_valid && cfg.vif.dst_ready));
              2:do @(posedge cfg.vif.src_clk);while(!(cfg.vif.src_valid && cfg.vif.src_ready));
              default:@(negedge cfg.vif.src_clk);
            endcase
            #500;
            cfg.vif.src_rst_n=t.src_reset_n;cfg.vif.dst_rst_n=t.dst_reset_n;#500;
          end
          default:`uvm_fatal("MC_CFG","unknown role")
        endcase
        seq_item_port.item_done();
      end
    endtask
  endclass
  class mc_sample extends uvm_object;
    `uvm_object_utils(mc_sample)
    time stamp;int kind,mask;bit [15:0] id;bit [7:0] data;
    function new(string name="mc_sample");super.new(name);endfunction
  endclass
  class mc_monitor extends uvm_monitor;
    `uvm_component_utils(mc_monitor)
    mc_config cfg;uvm_analysis_port#(mc_sample) observed;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    task run_phase(uvm_phase phase);
      int order,last_mask=3;void'($value$plusargs("MONITOR_ORDER=%d",order));
      forever begin
        mc_sample t;
        if(cfg.role==0)begin
          @(posedge cfg.vif.src_clk);
          if(!(cfg.vif.src_rst_n && cfg.vif.dst_rst_n && cfg.vif.src_valid && cfg.vif.src_ready))continue;
          t=mc_sample::type_id::create("source");t.kind=0;t.id=cfg.vif.src_id;t.data=cfg.vif.src_data;
        end else if(cfg.role==1)begin
          @(posedge cfg.vif.dst_clk);
          if(!(cfg.vif.src_rst_n && cfg.vif.dst_rst_n && cfg.vif.dst_valid && cfg.vif.dst_ready))continue;
          t=mc_sample::type_id::create("destination");t.kind=1;t.id=cfg.vif.dst_id;t.data=cfg.vif.dst_data;
        end else begin
          int mask;
          @(cfg.vif.src_rst_n or cfg.vif.dst_rst_n);mask=(cfg.vif.src_rst_n ? 0:1)|(cfg.vif.dst_rst_n ? 0:2);
          if(mask==last_mask)continue;
          last_mask=mask;t=mc_sample::type_id::create("reset");t.kind=2;t.mask=mask;
        end
        t.stamp=$time;
        $display("MC_OBS kind=%0d t=%0d id=%0d data=%0d mask=%0d",t.kind,t.stamp,t.id,t.data,t.mask);
        if(cfg.role==2)#500;
        else if((cfg.role==0 && order==0)||(cfg.role==1 && order==1))#1500;else #2000;
        observed.write(t);
      end
    endtask
  endclass
  class mc_agent extends uvm_agent;
    `uvm_component_utils(mc_agent)
    mc_config cfg;mc_driver driver;mc_monitor monitor;uvm_sequencer#(mc_item) sequencer;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(mc_config)::get(this,"","cfg",cfg)||cfg==null||cfg.vif==null||cfg.control==null)`uvm_fatal("MC_CFG","missing typed configuration")
      driver=mc_driver::type_id::create("driver",this);driver.cfg=cfg;
      monitor=mc_monitor::type_id::create("monitor",this);monitor.cfg=cfg;
      sequencer=new("sequencer",this);
    endfunction
    function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
  endclass
  class mc_bucket;
    mc_sample source,destination,reset;
  endclass
  class mc_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(mc_scoreboard)
    uvm_analysis_imp#(mc_sample,mc_scoreboard) observed;
    mc_bucket buckets[time];int expected[int],epoch_for[int];time accepted_at[int];bit seen[int];
    int epoch,accepted,produced,cancelled,last_mask=3,first_release;
    bit both_active,source_reset_seen,destination_reset_seen,source_first_seen,destination_first_seen,recovered,arrival_order;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    function void build_phase(uvm_phase phase);super.build_phase(phase);void'($value$plusargs("ARRIVAL_ORDER=%d",arrival_order));endfunction
    function void fail(string id,string reason);$display("CHECK_FAIL %s",id);`uvm_fatal(id,reason) endfunction
    function void write(mc_sample t);
      $display("MC_ARRIVE kind=%0d t=%0d at=%0d",t.kind,t.stamp,$time);
      if(!buckets.exists(t.stamp))buckets[t.stamp]=new;
      case(t.kind)
        0:begin if(buckets[t.stamp].source!=null)fail("MC_DUPLICATE","duplicate source observation");buckets[t.stamp].source=t;end
        1:begin if(buckets[t.stamp].destination!=null)fail("MC_DUPLICATE","duplicate destination observation");buckets[t.stamp].destination=t;end
        2:begin if(buckets[t.stamp].reset!=null)fail("MC_DUPLICATE","duplicate reset observation");buckets[t.stamp].reset=t;end
      endcase
      // Diagnostic: judging in arrival order instead of edge-time order must be detected.
      if(arrival_order)drain($time);
    endfunction
    function void drain(time limit_time);
      time stamp;
      while(buckets.first(stamp) && stamp<=limit_time)begin
        mc_bucket b=buckets[stamp];
        if(b.reset!=null)begin
          int mask=b.reset.mask;
          $display("MC_PROCESS kind=2 t=%0d id=0 data=0 mask=%0d",stamp,mask);
          if((mask & ~last_mask)!=0)begin
            epoch++;cancelled+=expected.num();expected.delete();epoch_for.delete();accepted_at.delete();
            if(mask==1)source_reset_seen=1;if(mask==2)destination_reset_seen=1;
            if(mask==3)begin both_active=1;first_release=0;end
          end
          if(both_active && last_mask==3 && mask!=3)first_release=mask;
          if(both_active && mask==0)begin
            if(first_release==2)source_first_seen=1;
            if(first_release==1)destination_first_seen=1;
            both_active=0;
          end
          last_mask=mask;
        end
        if(b.source!=null)begin
          int id=b.source.id;
          $display("MC_PROCESS kind=0 t=%0d id=%0d data=%0d mask=0",stamp,id,b.source.data);
          if(seen.exists(id))fail("MC_DUPLICATE","transaction ID was reused across reset epochs");
          seen[id]=1;expected[id]=int'(b.source.data)^8'h3c;epoch_for[id]=epoch;accepted_at[id]=stamp;accepted++;
          if(expected.num()>1)fail("MC_COUNTS","a lost completion or reset observation left multiple requests");
        end
        if(b.destination!=null)begin
          int id=b.destination.id;
          $display("MC_PROCESS kind=1 t=%0d id=%0d data=%0d mask=0",stamp,id,b.destination.data);
          if(!expected.exists(id) || epoch_for[id]!=epoch)fail("MC_STALE","unknown or cancelled-epoch response");
          if(stamp<=accepted_at[id] || int'(b.destination.data)!=expected[id])fail("MC_DATA","response differs from acceptance-time expectation");
          expected.delete(id);epoch_for.delete(id);accepted_at.delete(id);produced++;
          if(epoch>0)recovered=1;
        end
        if(accepted!=produced+cancelled+expected.num())fail("MC_COUNTS","accept/complete/cancel ledger differs");
        buckets.delete(stamp);
      end
    endfunction
    task run_phase(uvm_phase phase);
      forever begin #1000;if($time>=3000)drain($time-3000);end
    endtask
  endclass
  class mc_env extends uvm_env;
    `uvm_component_utils(mc_env)
    virtual mc_if vif;mc_control control;mc_agent agents[3];mc_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      string names[3]='{"source","destination","resets"};super.build_phase(phase);
      if(!uvm_config_db#(virtual mc_if)::get(this,"","vif",vif))`uvm_fatal("MC_CFG","missing interfaces")
      control=mc_control::type_id::create("control");scoreboard=mc_scoreboard::type_id::create("scoreboard",this);
      for(int i=0;i<3;i++)begin
        mc_config c=mc_config::type_id::create(names[i]);c.role=i;c.vif=vif;c.control=control;
        uvm_config_db#(mc_config)::set(this,names[i],"cfg",c);agents[i]=mc_agent::type_id::create(names[i],this);
      end
    endfunction
    function void connect_phase(uvm_phase phase);
      int off;void'($value$plusargs("CHECKER_OFF=%d",off));
      for(int i=0;i<3;i++)if(!((off==1 && i==0)||(off==2 && i==2)))agents[i].monitor.observed.connect(scoreboard.observed);
    endfunction
  endclass
  class mc_single extends uvm_sequence#(mc_item);
    `uvm_object_utils(mc_single)
    mc_item item;
    function new(string name="mc_single");super.new(name);endfunction
    task body();start_item(item);finish_item(item);endtask
  endclass
  class mc_ready extends uvm_sequence#(mc_item);
    `uvm_object_utils(mc_ready)
    mc_control control;int unsigned state;
    function new(string name="mc_ready");super.new(name);endfunction
    task body();
      while(!control.stop_sink)begin
        mc_item t=mc_item::type_id::create("ready");start_item(t);state=state*1664525+1013904223;t.ready=state[3:2]!=0;finish_item(t);
      end
    endtask
  endclass
  class mc_virtual extends uvm_sequence#(uvm_sequence_item);
    `uvm_object_utils(mc_virtual)
    mc_env env;int iterations,next_id=1;int unsigned state;
    function new(string name="mc_virtual");super.new(name);endfunction
    task send();
      mc_single s=mc_single::type_id::create("send");s.item=mc_item::type_id::create("request");
      state=state*1664525+1013904223;s.item.data=state[23:16];s.item.id=16'(next_id++);
      $display("MC_ISSUED id=%0d data=%0d",s.item.id,s.item.data);s.start(env.agents[0].sequencer);
      if(!s.item.accepted)env.scoreboard.fail("MC_STIMULUS","normal request was not accepted");
    endtask
    task reset_to(bit src_n,bit dst_n,int align=0);
      mc_single s=mc_single::type_id::create("reset");s.item=mc_item::type_id::create("reset_values");
      s.item.src_reset_n=src_n;s.item.dst_reset_n=dst_n;s.item.align=align;s.start(env.agents[2].sequencer);
    endtask
    task await_state(int wanted);
      for(int i=0;i<1000;i++)begin
        #1000;
        if(wanted==0 && env.scoreboard.expected.num()==0)return;
        if(wanted==1 && env.scoreboard.expected.num()==1 && env.vif.dst_valid)return;
      end
      env.scoreboard.fail("MC_DRAIN","expected acceptance, cancellation or drain did not complete");
    endtask
    // A completion half a nanosecond before a reset: observed first, but its notification arrives second.
    task guided_completion();
      env.control.force_stall=1;send();await_state(1);repeat(3)@(posedge env.vif.dst_clk);
      fork reset_to(0,1,1);begin #1000;env.control.force_stall=0;end join
      repeat(3)@(negedge env.vif.src_clk);reset_to(1,1);send();await_state(0);
    endtask
    // An acceptance half a nanosecond before a reset: the reset must cancel it although it is notified first.
    task guided_acceptance();
      fork send();reset_to(1,0,2);join
      repeat(3)@(negedge env.vif.src_clk);reset_to(1,1);send();await_state(0);
    endtask
    task body();
      int swap;
      mc_ready ready=mc_ready::type_id::create("ready_sequence");ready.control=env.control;ready.state=state^32'h89abcdef;
      fork ready.start(env.agents[1].sequencer);join_none
      reset_to(0,0);repeat(3)@(negedge env.vif.src_clk);reset_to(1,0);repeat(3)@(negedge env.vif.src_clk);reset_to(1,1);
      repeat(4)send();await_state(0);
      for(int phase_id=0;phase_id<4;phase_id++)begin
        env.control.force_stall=1;send();await_state(1);repeat(3)@(posedge env.vif.dst_clk);
        if(phase_id==0)reset_to(0,1);else if(phase_id==1)reset_to(1,0);else reset_to(0,0);
        repeat(3)@(negedge env.vif.src_clk);
        if(phase_id==2)begin reset_to(1,0);repeat(3)@(negedge env.vif.src_clk);end
        if(phase_id==3)begin reset_to(0,1);repeat(3)@(negedge env.vif.dst_clk);end
        reset_to(1,1);env.control.force_stall=0;repeat(2)send();await_state(0);
      end
      void'($value$plusargs("GUIDED_SWAP=%d",swap));
      if(swap)begin guided_acceptance();guided_completion();end
      else begin guided_completion();guided_acceptance();end
      repeat(iterations)send();await_state(0);
      env.control.force_stall=1;send();await_state(1);repeat(3)@(posedge env.vif.dst_clk);
      env.control.force_stall=0;await_state(0);env.control.stop_sink=1;wait fork;#6000;
    endtask
  endclass
  class mc_test extends uvm_test;
    `uvm_component_utils(mc_test)
    mc_env env;int iterations=40,seed=17;bit finished;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);env=mc_env::type_id::create("env",this);
      void'($value$plusargs("ITERATIONS=%d",iterations));void'($value$plusargs("SEED=%d",seed));
    endfunction
    task run_phase(uvm_phase phase);
      mc_virtual scenario=mc_virtual::type_id::create("scenario");phase.raise_objection(this);
      scenario.env=env;scenario.iterations=iterations;scenario.state=seed;
      $display("MC_OWNERSHIP source=1 destination=1 resets=1");scenario.start(null);finished=1;phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      mc_scoreboard s=env.scoreboard;
      if(!finished || s.expected.num()!=0 || s.buckets.num()!=0 || s.accepted!=21+iterations || s.produced!=16+iterations || s.cancelled!=5 || s.epoch!=6 ||
         !s.source_reset_seen || !s.destination_reset_seen || !s.source_first_seen || !s.destination_first_seen || !s.recovered)
        s.fail("MC_COUNTS","missing data, reset epochs, release orders or observations");
    endfunction
    function void report_phase(uvm_phase phase);
      uvm_report_server server=uvm_report_server::get_server();mc_scoreboard s=env.scoreboard;
      if(server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)$fatal(1,"UVM errors");
      $display("MC_COMPLETE accepted=%0d produced=%0d cancelled=%0d epoch=%0d pending=0",s.accepted,s.produced,s.cancelled,s.epoch);
      $display("RESULT PASS checks=%0d",s.accepted);
    endfunction
  endclass
endpackage
