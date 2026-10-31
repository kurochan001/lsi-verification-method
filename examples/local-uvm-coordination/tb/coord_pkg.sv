`timescale 1ns/1ps
`include "uvm_macros.svh"
package coord_pkg;
  import uvm_pkg::*;
  import uvm_apb_pkg::*;
  `uvm_analysis_imp_decl(_cfg)
  `uvm_analysis_imp_decl(_data)

  class agent_config extends uvm_object;
    `uvm_object_utils(agent_config)
    virtual apb_if bus;
    virtual stream_if stream;
    int role;
    function new(string name="agent_config");super.new(name);endfunction
  endclass
  class cycle_command extends uvm_sequence_item;
    `uvm_object_utils(cycle_command)
    bit rst_n,sel,enable,write,valid,ready;
    bit [7:0] address,x;
    bit [31:0] data;
    function new(string name="cycle_command");super.new(name);endfunction
  endclass
  class replay_sequence extends uvm_sequence #(cycle_command);
    `uvm_object_utils(replay_sequence)
    function new(string name="replay_sequence");super.new(name);endfunction
    task body();
      string vectors;
      int fd,n,r,s,e,w,a,value,v,x,ready;
      if(!$value$plusargs("VECTORS=%s",vectors)) `uvm_fatal("COORD_INPUT","missing vectors")
      fd=$fopen(vectors,"r");if(!fd) `uvm_fatal("COORD_INPUT","cannot open vectors")
      while(!$feof(fd)) begin
        cycle_command t;
        n=$fscanf(fd,"%d %d %d %d %h %h %d %h %d\n",r,s,e,w,a,value,v,x,ready);
        if(n!=9) `uvm_fatal("COORD_INPUT","bad vector format")
        t=cycle_command::type_id::create("cycle");start_item(t);
        t.rst_n=r;t.sel=s;t.enable=e;t.write=w;t.address=a;t.data=value;t.valid=v;t.x=x;t.ready=ready;
        finish_item(t);
      end
      $fclose(fd);
    endtask
  endclass
  class role_driver extends uvm_driver #(cycle_command);
    `uvm_component_utils(role_driver)
    agent_config cfg;
    int issued;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    task run_phase(uvm_phase phase);
      forever begin
        cycle_command t;seq_item_port.get_next_item(t);
        @(negedge cfg.bus.clk);
        case(cfg.role)
          0:begin
            cfg.bus.rst_n=t.rst_n;cfg.bus.psel=t.sel;cfg.bus.penable=t.enable;
            cfg.bus.pwrite=t.write;cfg.bus.paddr=t.address;cfg.bus.pwdata=t.data;cfg.bus.events=0;
            cfg.stream.recording=1;
          end
          1:begin cfg.stream.input_valid=t.valid;cfg.stream.input_data=t.x;end
          2:cfg.stream.output_ready=t.ready;
          default:`uvm_fatal("COORD_ROLE","unknown drive role")
        endcase
        @(posedge cfg.bus.clk);#3;issued++;seq_item_port.item_done();
      end
    endtask
  endclass
  class cfg_sample extends uvm_object;
    `uvm_object_utils(cfg_sample)
    int edge_id;
    bit rst_n,write;
    bit [7:0] value;
    function new(string name="cfg_sample");super.new(name);endfunction
  endclass
  class data_sample extends uvm_object;
    `uvm_object_utils(data_sample)
    int edge_id;
    bit rst_n,valid,ready,out_valid,out_ready,post_valid;
    bit [7:0] x,out_data,post_data;
    function new(string name="data_sample");super.new(name);endfunction
  endclass
  class cfg_monitor extends uvm_monitor;
    `uvm_component_utils(cfg_monitor)
    agent_config cfg;
    uvm_analysis_port #(cfg_sample) observed;
    int samples;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    task run_phase(uvm_phase phase);
      int order,drop;
      void'($value$plusargs("MONITOR_ORDER=%d",order));void'($value$plusargs("DROP_CFG=%d",drop));
      forever begin
        cfg_sample t;@(posedge cfg.bus.clk);if(!cfg.stream.recording)continue;
        t=cfg_sample::type_id::create("cfg_edge");samples++;t.edge_id=samples;t.rst_n=cfg.bus.rst_n;
        t.write=cfg.bus.psel && cfg.bus.penable && cfg.bus.pready && !cfg.bus.pslverr && cfg.bus.pwrite && cfg.bus.paddr==0;
        t.value=cfg.bus.pwdata[7:0];
        if(order==0) #1; else #2;
        if(!(drop && samples==2))observed.write(t);
      end
    endtask
  endclass
  class data_monitor extends uvm_monitor;
    `uvm_component_utils(data_monitor)
    agent_config cfg;
    uvm_analysis_port #(data_sample) observed;
    int samples;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    task run_phase(uvm_phase phase);
      int order;void'($value$plusargs("MONITOR_ORDER=%d",order));
      forever begin
        data_sample t;@(posedge cfg.bus.clk);if(!cfg.stream.recording)continue;
        t=data_sample::type_id::create("data_edge");samples++;t.edge_id=samples;t.rst_n=cfg.bus.rst_n;
        t.valid=cfg.stream.input_valid;t.x=cfg.stream.input_data;t.ready=cfg.stream.input_ready;
        t.out_valid=cfg.stream.output_valid;t.out_ready=cfg.stream.output_ready;t.out_data=cfg.stream.output_data;
        #1;t.post_valid=cfg.stream.output_valid;t.post_data=cfg.stream.output_data;
        if(order==0) #1;
        observed.write(t);
      end
    endtask
  endclass
  class coord_agent extends uvm_agent;
    `uvm_component_utils(coord_agent)
    agent_config cfg;
    role_driver driver;
    uvm_sequencer #(cycle_command) sequencer;
    cfg_monitor configuration_monitor;
    data_monitor stream_monitor;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(agent_config)::get(this,"","cfg",cfg) || cfg==null || cfg.bus==null || cfg.stream==null)
        `uvm_fatal("COORD_CFG","incomplete agent configuration")
      driver=role_driver::type_id::create("driver",this);driver.cfg=cfg;sequencer=new("sequencer",this);
      if(cfg.role==0)begin configuration_monitor=cfg_monitor::type_id::create("monitor",this);configuration_monitor.cfg=cfg;end
      if(cfg.role==1)begin stream_monitor=data_monitor::type_id::create("monitor",this);stream_monitor.cfg=cfg;end
    endfunction
    function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
  endclass

  class edge_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(edge_scoreboard)
    uvm_analysis_imp_cfg #(cfg_sample,edge_scoreboard) configuration;
    uvm_analysis_imp_data #(data_sample,edge_scoreboard) data;
    cfg_sample configurations[int];data_sample samples[int];
    int expected[$];
    int closed,accepted,produced,cancelled,stalls,overlaps,reset_pending,coverage_samples;
    bit [7:0] gain;
    bit cover_off;
    covergroup measured with function sample(int gain_kind,int operand_kind,bit saturation,bit overlap);
      option.per_instance=1;
      cp_gain:coverpoint gain_kind { bins zero={0};bins one={1};bins multi={2};bins maximum={3}; }
      cp_operand:coverpoint operand_kind {bins zero={0};bins one={1};bins wide_value={2};}
      cp_saturation:coverpoint saturation {bins absent={0};bins present={1};}
      cp_overlap:coverpoint overlap {bins absent={0};bins present={1};}
      gain_operand:cross cp_gain,cp_operand;
    endgroup
    function new(string name,uvm_component parent);
      super.new(name,parent);configuration=new("configuration",this);data=new("data",this);measured=new;
    endfunction
    function void build_phase(uvm_phase phase);
      int off;super.build_phase(phase);void'($value$plusargs("COVER_OFF=%d",off));cover_off=off;
    endfunction
    function void fail(string id,string reason);
      $display("CHECK_FAIL %s",id);`uvm_fatal(id,reason)
    endfunction
    function void write_cfg(cfg_sample t);
      if(configurations.exists(t.edge_id))fail("COORD_DUPLICATE","duplicate configuration edge");
      configurations[t.edge_id]=t;drain();
    endfunction
    function void write_data(data_sample t);
      if(samples.exists(t.edge_id))fail("COORD_DUPLICATE","duplicate data edge");
      samples[t.edge_id]=t;drain();
    endfunction
    function void drain();
      while(configurations.exists(closed+1) && samples.exists(closed+1)) begin
        cfg_sample c=configurations[closed+1];data_sample d=samples[closed+1];
        int product,result,discarded;
        if(c.rst_n!=d.rst_n)fail("COORD_EDGE","reset epochs differ");
        if(!d.rst_n)begin
          if(d.post_valid)fail("COORD_RESET","reset did not discard the output");
          if(expected.size()!=0)begin cancelled+=expected.size();reset_pending++;end
          expected.delete();gain=0;
        end else begin
          if(d.ready!=(expected.size()==0 || d.out_ready) || d.out_valid!=(expected.size()!=0))
            fail("COORD_HANDSHAKE","ready/valid differs from independent queue");
          if(d.out_valid && d.out_data!=expected[0])fail("COORD_DATA","output differs from acceptance-time expectation");
          if(d.out_valid && !d.out_ready)stalls++;
          if(d.out_valid && d.out_ready)begin discarded=expected.pop_front();produced++;end
          if(d.valid && d.ready)begin
            product=int'(d.x)*int'(gain);result=product>255 ? 255:product;
            expected.push_back(result);accepted++;if(c.write)overlaps++;
            if(!cover_off)begin
              measured.sample(gain==0 ? 0:gain==1 ? 1:gain==255 ? 3:2,
                              d.x==0 ? 0:d.x==1 ? 1:2,product>255,c.write);coverage_samples++;
            end
          end
          // Configuration changes become visible only after this edge's input.
          if(c.write)gain=c.value;
          if(d.post_valid!=(expected.size()!=0) || (d.post_valid && d.post_data!=expected[0]))
            fail("COORD_DATA","post-update result differs");
        end
        $display("COORD_SAMPLE %0d %0d %0d %0d %0d %0d %0d",closed+1,d.ready,d.out_valid,d.out_data,d.post_valid,d.post_data,gain);
        configurations.delete(closed+1);samples.delete(closed+1);closed++;
      end
    endfunction
  endclass

  class coordinator extends uvm_sequence #(cycle_command);
    `uvm_object_utils(coordinator)
    uvm_sequencer #(cycle_command) cfg_sequencer,data_sequencer,ready_sequencer;
    function new(string name="coordinator");super.new(name);endfunction
    task body();
      replay_sequence configuration=replay_sequence::type_id::create("configuration");
      replay_sequence data=replay_sequence::type_id::create("data");
      replay_sequence ready=replay_sequence::type_id::create("ready");
      if(cfg_sequencer==null || data_sequencer==null || ready_sequencer==null)`uvm_fatal("COORD_CFG","missing child sequencer")
      fork configuration.start(cfg_sequencer);data.start(data_sequencer);ready.start(ready_sequencer);join
    endtask
  endclass
  class coord_test extends uvm_test;
    `uvm_component_utils(coord_test)
    coord_agent configuration,data,ready;
    edge_scoreboard scoreboard;
    virtual apb_if bus;virtual stream_if stream;
    int planned;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      string names[3]='{"configuration","data","ready"};
      super.build_phase(phase);
      if(!uvm_config_db#(virtual apb_if)::get(this,"","bus",bus) ||
         !uvm_config_db#(virtual stream_if)::get(this,"","stream",stream))`uvm_fatal("COORD_CFG","missing interfaces")
      if(!$value$plusargs("CHECKS=%d",planned) || planned<=0)`uvm_fatal("COORD_CFG","missing plan")
      for(int i=0;i<3;i++)begin
        agent_config cfg=agent_config::type_id::create(names[i]);cfg.bus=bus;cfg.stream=stream;cfg.role=i;
        uvm_config_db#(agent_config)::set(this,names[i],"cfg",cfg);
      end
      configuration=coord_agent::type_id::create("configuration",this);data=coord_agent::type_id::create("data",this);ready=coord_agent::type_id::create("ready",this);
      scoreboard=edge_scoreboard::type_id::create("scoreboard",this);
    endfunction
    function void connect_phase(uvm_phase phase);
      int off;super.connect_phase(phase);void'($value$plusargs("CHECKER_OFF=%d",off));
      configuration.configuration_monitor.observed.connect(scoreboard.configuration);
      if(!off)data.stream_monitor.observed.connect(scoreboard.data);
    endfunction
    task run_phase(uvm_phase phase);
      coordinator scenario=coordinator::type_id::create("scenario");
      phase.raise_objection(this);
      scenario.cfg_sequencer=configuration.sequencer;scenario.data_sequencer=data.sequencer;scenario.ready_sequencer=ready.sequencer;
      $display("COORD_OWNERSHIP config=1 data=1 ready=1");scenario.start(null);
      stream.recording=0;#1;phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if(scoreboard.closed!=planned || scoreboard.configurations.num()!=0 || scoreboard.samples.num()!=0 ||
         configuration.driver.issued!=planned || data.driver.issued!=planned || ready.driver.issued!=planned ||
         scoreboard.expected.size()!=0 || scoreboard.accepted<=0 || scoreboard.stalls<=0 || scoreboard.overlaps<=0 || scoreboard.reset_pending<=0 ||
         scoreboard.accepted!=scoreboard.produced+scoreboard.cancelled)
        scoreboard.fail("COORD_COUNTS","missing edges, comparisons, drain or required interaction");
      if(scoreboard.coverage_samples!=scoreboard.accepted)scoreboard.fail("COORD_COVERAGE","coverage sampling was disabled");
    endfunction
    function void report_phase(uvm_phase phase);
      uvm_report_server server=uvm_report_server::get_server();super.report_phase(phase);
      if(server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)$fatal(1,"UVM report contains errors");
      $display("COORD_COMPLETE cycles=%0d accepted=%0d produced=%0d cancelled=%0d pending=0",scoreboard.closed,scoreboard.accepted,scoreboard.produced,scoreboard.cancelled);
      $display("RESULT PASS checks=%0d",scoreboard.closed);
    endfunction
  endclass
endpackage
