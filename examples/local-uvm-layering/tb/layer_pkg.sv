`timescale 1ns/1ps
`include "uvm_macros.svh"
package layer_pkg;
  import uvm_pkg::*;
  localparam int CTRL=0,DATA=1,INDEX=2,VALUE=3,STATUS=4,ENABLE=5;
  localparam int SRC_FRAME=0,SRC_STATS=1,SRC_HOLD=2,SRC_LATE=3,SRC_ISR=4,SRC_SETUP=5;
  // Longest lock in this testbench is four transfers; one more may already be granted.
  localparam int LATENCY_BOUND=5;

  class fatal_to_exit extends uvm_report_catcher;
    function new(string n="fatal_to_exit");super.new(n);endfunction
    virtual function action_e catch();if(get_severity()==UVM_FATAL)$fatal(1,"UVM_FATAL %s",get_id());return THROW;endfunction
  endclass

  class bus_item extends uvm_sequence_item;
    `uvm_object_utils(bus_item)
    int src;bit write,irq_before;bit [2:0] addr;bit [7:0] wdata,rdata;
    function new(string n="bus_item");super.new(n);endfunction
  endclass
  class packet_item extends uvm_sequence_item;
    `uvm_object_utils(packet_item)
    bit port;bit [6:0] seq;bit [7:0] payload[$];int gap;
    function new(string n="packet_item");super.new(n);endfunction
    function bit [7:0] head();return {port,seq};endfunction
    function bit [7:0] sum();
      bit [7:0] s=head();
      foreach(payload[i])s+=payload[i];
      return s;
    endfunction
  endclass
  class frame_obs extends uvm_object;
    `uvm_object_utils(frame_obs)
    bit [7:0] head,len,sum;
    function new(string n="frame_obs");super.new(n);endfunction
  endclass

  // Shared between the sequences, the scenario and the scoreboard.
  class layer_ctl extends uvm_object;
    `uvm_object_utils(layer_ctl)
    virtual layer_if vif;
    bit lock_off,isr_lock,arb_fifo,flat;
    uvm_event gap_open,hold_locked,late_requested,status_read,clearing;
    packet_item expected[$];
    int sent,delivered,alarms,served_done,served_alarm,services,urgent_left;
    bit backlog,isr_busy;
    function new(string n="layer_ctl");
      super.new(n);gap_open=new("gap_open");hold_locked=new("hold_locked");late_requested=new("late_requested");
      status_read=new("status_read");clearing=new("clearing");
    endfunction
  endclass

  class bus_driver extends uvm_driver #(bus_item);
    `uvm_component_utils(bus_driver)
    virtual layer_if vif;int issued;
    uvm_analysis_port #(bus_item) done;
    function new(string n,uvm_component p);super.new(n,p);done=new("done",this);endfunction
    task run_phase(uvm_phase phase);
      forever begin
        bus_item t;seq_item_port.get_next_item(t);
        @(negedge vif.clk);vif.req=1;vif.write=t.write;vif.addr=t.addr;vif.wdata=t.wdata;
        @(negedge vif.clk);vif.req=0;vif.write=0;t.rdata=vif.rdata;issued++;
        $display("LAYER_XFER %0d %0d %0d %0d %0d %0d",issued,t.src,t.write,t.addr,t.wdata,t.rdata);
        done.write(t);seq_item_port.item_done();
      end
    endtask
  endclass

  class bus_monitor extends uvm_monitor;
    `uvm_component_utils(bus_monitor)
    virtual layer_if vif;
    uvm_analysis_port #(bus_item) transfers;
    uvm_analysis_port #(frame_obs) frames;
    function new(string n,uvm_component p);super.new(n,p);transfers=new("transfers",this);frames=new("frames",this);endfunction
    task run_phase(uvm_phase phase);
      forever begin
        @(negedge vif.clk);
        if(vif.tap_req===1'b1)begin
          bus_item t=bus_item::type_id::create("observed");
          if(vif.ack!==1'b1)begin $display("CHECK_FAIL LAYER_BUS");`uvm_fatal("LAYER_BUS","transfer was not acknowledged") end
          t.write=vif.tap_write;t.addr=vif.tap_addr;t.wdata=vif.tap_wdata;t.rdata=vif.rdata;t.irq_before=vif.tap_irq;transfers.write(t);
        end
        if(vif.frame_valid===1'b1)begin
          frame_obs f=frame_obs::type_id::create("frame");f.head=vif.frame_head;f.len=vif.frame_len;f.sum=vif.frame_sum;frames.write(f);
        end
      end
    endtask
  endclass

  `uvm_analysis_imp_decl(_driven)
  `uvm_analysis_imp_decl(_observed)
  `uvm_analysis_imp_decl(_frame)
  class layer_scoreboard extends uvm_component;
    `uvm_component_utils(layer_scoreboard)
    uvm_analysis_imp_driven #(bus_item,layer_scoreboard) driven;
    uvm_analysis_imp_observed #(bus_item,layer_scoreboard) observed;
    uvm_analysis_imp_frame #(frame_obs,layer_scoreboard) frame;
    layer_ctl ctl;
    bus_item driven_q[$],observed_q[$];
    frame_obs bus_frames[$],dut_frames[$];
    bit in_frame;bit [7:0] bytes[$];
    bit [1:0] index;int index_owner=-1;
    bit [7:0] table_values[4];
    int transfers,streak,pairs;
    function new(string n,uvm_component p);
      super.new(n,p);driven=new("driven",this);observed=new("observed",this);frame=new("frame",this);
    endfunction
    function void fail(string id,string reason);
      $display("CHECK_FAIL %s",id);`uvm_fatal(id,reason)
    endfunction
    function void write_driven(bus_item t);driven_q.push_back(t);drain();endfunction
    function void write_observed(bus_item t);observed_q.push_back(t);drain();endfunction
    function void write_frame(frame_obs t);dut_frames.push_back(t);drain();endfunction
    function void close_frame();
      frame_obs f=frame_obs::type_id::create("assembled");
      bit [7:0] s=0;
      foreach(bytes[i])s+=bytes[i];
      f.head=bytes.size()==0 ? 8'h00:bytes[0];f.len=8'(bytes.size());f.sum=s;bus_frames.push_back(f);
      table_values[0]=f.len;table_values[1]=f.sum;table_values[2]++;
    endfunction
    function void drain();
      while(driven_q.size()!=0 && observed_q.size()!=0)begin
        bus_item d=driven_q.pop_front(),m=observed_q.pop_front();
        transfers++;
        if(d.write!=m.write || d.addr!=m.addr || (d.write && d.wdata!=m.wdata) || (!d.write && d.rdata!=m.rdata))
          fail("LAYER_BUS","driver item and observed transfer differ");
        // A pending interrupt may wait only for work that was already granted or locked.
        if(m.irq_before && d.src!=SRC_ISR)begin
          streak++;
          if(streak>LATENCY_BOUND)fail("LAYER_LATENCY","interrupt service waited behind too many transfers");
        end else streak=0;
        if(m.write && m.addr==CTRL && m.wdata[0])begin
          if(in_frame)fail("LAYER_FRAME","a frame started inside another frame");
          in_frame=1;bytes.delete();
        end else if(m.write && m.addr==CTRL && m.wdata[1])begin
          if(!in_frame)fail("LAYER_FRAME","a frame ended without a start");
          in_frame=0;close_frame();
        end else if(m.write && m.addr==DATA)begin
          if(!in_frame)fail("LAYER_FRAME","a byte was written outside a frame");
          bytes.push_back(m.wdata);
        end else if(m.write && m.addr==INDEX)begin
          index=m.wdata[1:0];index_owner=d.src;
        end else if(!m.write && m.addr==VALUE)begin
          if(index_owner!=d.src)fail("LAYER_ATOMIC","another sequence changed the index before the read");
          if(m.rdata!=table_values[index])fail("LAYER_VALUE","indirect value differs from the frames seen on the bus");
          pairs++;
        end
      end
      while(bus_frames.size()!=0 && dut_frames.size()!=0)begin
        frame_obs b=bus_frames.pop_front(),f=dut_frames.pop_front();
        packet_item e;
        if(b.head!=f.head || b.len!=f.len || b.sum!=f.sum)fail("LAYER_DATA","DUT frame differs from the bytes on the bus");
        if(ctl.expected.size()==0)fail("LAYER_TRANSLATE","a frame arrived without an upper-level packet");
        e=ctl.expected.pop_front();
        if(e.head()!=f.head || 8'(e.payload.size()+1)!=f.len || e.sum()!=f.sum)fail("LAYER_TRANSLATE","frame differs from the upper-level packet");
        if(ctl.backlog && ctl.urgent_left>0)begin
          if(!e.port)fail("LAYER_PRIORITY","a low-priority packet went ahead of a waiting high-priority packet");
          ctl.urgent_left--;
        end
        ctl.delivered++;
      end
    endfunction
    function bit idle();
      return driven_q.size()==0 && observed_q.size()==0 && bus_frames.size()==0 && dut_frames.size()==0 && ctl.expected.size()==0 && !in_frame;
    endfunction
  endclass

  // Upper level: a stream of packets for one port.
  class packet_seq extends uvm_sequence #(packet_item);
    `uvm_object_utils(packet_seq)
    packet_item packets[$];layer_ctl ctl;
    function new(string n="packet_seq");super.new(n);endfunction
    task body();
      foreach(packets[i])begin
        repeat(packets[i].gap)@(negedge ctl.vif.clk);
        start_item(packets[i]);finish_item(packets[i]);
      end
    endtask
  endclass

  class bus_seq extends uvm_sequence #(bus_item);
    `uvm_object_utils(bus_seq)
    layer_ctl ctl;int src;
    function new(string n="bus_seq");super.new(n);endfunction
    task transfer(bit write,int addr,bit [7:0] wdata,output bit [7:0] rdata);
      bus_item t=bus_item::type_id::create("t");
      start_item(t);t.src=src;t.write=write;t.addr=3'(addr);t.wdata=wdata;finish_item(t);rdata=t.rdata;
    endtask
    task wr(int addr,bit [7:0] value);bit [7:0] unused;transfer(1,addr,value,unused);endtask
    task rd(int addr,output bit [7:0] value);transfer(0,addr,8'h00,value);endtask
    task frame(packet_item p);
      wr(CTRL,8'h01);wr(DATA,p.head());
      foreach(p.payload[i])wr(DATA,p.payload[i]);
      wr(CTRL,8'h02);
    endtask
  endclass

  // Lower level: takes one packet at a time from the upper sequencer and turns it into bus transfers.
  class layer_seq extends bus_seq;
    `uvm_object_utils(layer_seq)
    uvm_sequencer #(packet_item) upper;
    function new(string n="layer_seq");super.new(n);src=SRC_FRAME;endfunction
    task body();
      forever begin
        packet_item p;upper.get_next_item(p);
        ctl.expected.push_back(p);ctl.sent++;frame(p);
        upper.item_done();
      end
    endtask
  endclass

  // The alternative without layering: each port writes its own frames straight to the bus sequencer.
  class flat_seq extends bus_seq;
    `uvm_object_utils(flat_seq)
    packet_item packets[$];
    function new(string n="flat_seq");super.new(n);src=SRC_FRAME;endfunction
    task body();
      foreach(packets[i])begin ctl.expected.push_back(packets[i]);ctl.sent++;frame(packets[i]);end
    endtask
  endclass

  // INDEX write followed by VALUE read; the pair must not be separated by another writer of INDEX.
  class pair_seq extends bus_seq;
    `uvm_object_utils(pair_seq)
    int selections[$],gap;
    uvm_event before_lock,after_lock,after_index;
    function new(string n="pair_seq");super.new(n);endfunction
    task body();
      bit [7:0] value;
      if(before_lock!=null)before_lock.trigger();
      if(!ctl.lock_off)lock();
      if(after_lock!=null)after_lock.trigger();
      foreach(selections[i])begin
        wr(INDEX,8'(selections[i]));
        if(i==0 && after_index!=null)after_index.trigger();
        repeat(gap)@(negedge ctl.vif.clk);
        rd(VALUE,value);
      end
      if(!ctl.lock_off)unlock();
    endtask
  endclass

  class setup_seq extends bus_seq;
    `uvm_object_utils(setup_seq)
    function new(string n="setup_seq");super.new(n);src=SRC_SETUP;endfunction
    task body();wr(ENABLE,8'h07);endtask
  endclass

  // Interrupt service: goes ahead of everything that is still waiting.
  class isr_seq extends bus_seq;
    `uvm_object_utils(isr_seq)
    function new(string n="isr_seq");super.new(n);src=SRC_ISR;endfunction
    task body();
      forever begin
        bit [7:0] status,value;
        do @(negedge ctl.vif.clk); while(ctl.vif.irq!==1'b1);
        ctl.isr_busy=1;
        if(ctl.isr_lock)lock();else grab();
        rd(STATUS,status);ctl.status_read.trigger();
        if(status[0])begin wr(INDEX,8'h00);rd(VALUE,value);wr(INDEX,8'h01);rd(VALUE,value);end
        if(status[1])begin wr(INDEX,8'h03);rd(VALUE,value);end
        ctl.clearing.trigger();wr(STATUS,status);
        if(ctl.isr_lock)unlock();else ungrab();
        ctl.served_done+=int'(status[0]);ctl.served_alarm+=int'(status[1]);ctl.services++;ctl.isr_busy=0;
      end
    endtask
  endclass

  // The scenario: a virtual sequence. It owns no item; it starts sequences on two sequencers and drives the alarm pin.
  class layer_vseq extends uvm_sequence #(uvm_sequence_item);
    `uvm_object_utils(layer_vseq)
    uvm_sequencer #(bus_item) bus_sequencer;
    uvm_sequencer #(packet_item) upper_sequencer;
    layer_ctl ctl;layer_scoreboard scoreboard;
    packet_item pool[2][$];
    int steps[$]; // nine fields per step
    function new(string n="layer_vseq");super.new(n);endfunction
    function void fail(string id,string reason);scoreboard.fail(id,reason);endfunction
    task pulse();
      @(negedge ctl.vif.clk);ctl.vif.alarm=1;ctl.alarms++;
      @(negedge ctl.vif.clk);ctl.vif.alarm=0;
    endtask
    task quiesce();
      int waited=0;
      forever begin
        @(negedge ctl.vif.clk);
        if(ctl.delivered==ctl.sent && ctl.served_done==ctl.delivered && ctl.served_alarm==ctl.alarms &&
           !ctl.isr_busy && ctl.vif.irq===1'b0 && scoreboard.idle())break;
        waited++;
        if(waited>600)begin
          if(ctl.served_alarm!=ctl.alarms || ctl.served_done!=ctl.delivered)fail("LAYER_IRQ","an interrupt cause was not serviced");
          fail("LAYER_COUNTS","traffic did not drain");
        end
      end
      repeat(2)@(negedge ctl.vif.clk);
    endtask
    function packet_seq stream(bit port,int count);
      packet_seq s=packet_seq::type_id::create(port ? "urgent":"bulk");
      s.ctl=ctl;
      repeat(count)begin
        if(pool[port].size()==0)fail("LAYER_PLAN","plan has too few packets");
        s.packets.push_back(pool[port].pop_front());
      end
      return s;
    endfunction
    function pair_seq pair(int src,int first,int second,int gap);
      pair_seq s=pair_seq::type_id::create("pair");
      s.ctl=ctl;s.src=src;s.gap=gap;s.selections.push_back(first);
      if(second>=0)s.selections.push_back(second);
      return s;
    endfunction
    task traffic(int urgent_count,int bulk_count);
      packet_seq bulk=stream(0,bulk_count),urgent=stream(1,urgent_count);
      if(ctl.flat)begin
        flat_seq a=flat_seq::type_id::create("flat_bulk"),b=flat_seq::type_id::create("flat_urgent");
        a.ctl=ctl;b.ctl=ctl;a.packets=bulk.packets;b.packets=urgent.packets;
        fork a.start(bus_sequencer,this);b.start(bus_sequencer,this);join
      end else begin
        fork bulk.start(upper_sequencer,this,100);urgent.start(upper_sequencer,this,200);join
      end
    endtask
    task body();
      layer_seq translator=layer_seq::type_id::create("translator");
      isr_seq isr=isr_seq::type_id::create("isr");
      setup_seq setup=setup_seq::type_id::create("setup");
      translator.ctl=ctl;translator.upper=upper_sequencer;isr.ctl=ctl;setup.ctl=ctl;
      ctl.vif.rst_n=0;repeat(2)@(negedge ctl.vif.clk);ctl.vif.recording=1;
      @(negedge ctl.vif.clk);ctl.vif.rst_n=1;@(negedge ctl.vif.clk);
      setup.start(bus_sequencer,this);
      fork translator.start(bus_sequencer,this);isr.start(bus_sequencer,this);join_none
      for(int i=0;i<steps.size()/9;i++)begin
        int kind=steps[9*i],a=steps[9*i+1],b=steps[9*i+2],c=steps[9*i+3],d=steps[9*i+4],e=steps[9*i+5];
        $display("LAYER_STEP %0d %0d begin",i,kind);
        case(kind)
          1:begin // both ports have everything queued before the lower level asks
            ctl.urgent_left=a;ctl.backlog=1;traffic(a,b);quiesce();ctl.backlog=0;
          end
          2:begin // an interrupt arrives between the two halves of a locked pair
            pair_seq stats=pair(SRC_STATS,a,-1,b);stats.after_index=ctl.gap_open;
            fork begin ctl.gap_open.wait_trigger();pulse();end join_none
            stats.start(bus_sequencer,this);quiesce();
          end
          3:begin // a grab requested after a lock is served before it
            pair_seq hold=pair(SRC_HOLD,2,3,0),late=pair(SRC_LATE,3,2,0);
            hold.after_lock=ctl.hold_locked;late.before_lock=ctl.late_requested;
            fork
              hold.start(bus_sequencer,this);
              begin ctl.hold_locked.wait_trigger();late.start(bus_sequencer,this);end
              begin ctl.late_requested.wait_trigger();pulse();end
            join
            quiesce();
          end
          4:begin // another cause arrives after the status was read and before it is cleared
            fork begin ctl.status_read.wait_trigger();pulse();end join_none
            traffic(0,1);quiesce();
          end
          5:begin // the same cause arrives again in the clock that clears it
            fork begin ctl.clearing.wait_trigger();pulse();end join_none
            pulse();quiesce();
          end
          6:begin // everything at once
            fork
              traffic(a,b);
              for(int n=0;n<c;n++)begin
                pair_seq stats=pair(SRC_STATS,n%2==0 ? 2:3,-1,(e+3*n)%4);
                repeat((e+n)%5)@(negedge ctl.vif.clk);
                stats.start(bus_sequencer,this);
              end
              for(int n=0;n<d;n++)begin
                int waited=0;
                repeat(3+(7*e+5*n)%11)@(negedge ctl.vif.clk);
                pulse();
                while(ctl.served_alarm!=ctl.alarms)begin
                  @(negedge ctl.vif.clk);waited++;
                  if(waited>600)fail("LAYER_IRQ","an alarm was not serviced");
                end
              end
            join
            quiesce();
          end
          default:fail("LAYER_PLAN","unknown step");
        endcase
        $display("LAYER_STEP %0d %0d end",i,kind);
      end
      translator.kill();isr.kill();
    endtask
  endclass

  class layer_test extends uvm_test;
    `uvm_component_utils(layer_test)
    uvm_sequencer #(bus_item) bus_sequencer;
    uvm_sequencer #(packet_item) upper_sequencer;
    bus_driver driver;bus_monitor monitor;layer_scoreboard scoreboard;
    layer_ctl ctl;virtual layer_if bus;
    layer_vseq scenario;
    int planned;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      int value;
      super.build_phase(phase);
      if(!uvm_config_db#(virtual layer_if)::get(this,"","bus",bus))`uvm_fatal("LAYER_CFG","missing interface")
      ctl=layer_ctl::type_id::create("ctl");ctl.vif=bus;
      if($value$plusargs("LOCK_OFF=%d",value))ctl.lock_off=value!=0;
      if($value$plusargs("ISR_LOCK=%d",value))ctl.isr_lock=value!=0;
      if($value$plusargs("ARB_FIFO=%d",value))ctl.arb_fifo=value!=0;
      if($value$plusargs("FLAT=%d",value))ctl.flat=value!=0;
      bus_sequencer=new("bus_sequencer",this);upper_sequencer=new("upper_sequencer",this);
      driver=bus_driver::type_id::create("driver",this);monitor=bus_monitor::type_id::create("monitor",this);
      scoreboard=layer_scoreboard::type_id::create("scoreboard",this);
      driver.vif=bus;monitor.vif=bus;scoreboard.ctl=ctl;
      scenario=layer_vseq::type_id::create("scenario");
      scenario.ctl=ctl;scenario.scoreboard=scoreboard;
      load_plan();
    endfunction
    function void load_plan();
      string name;int file,row[9];
      if(!$value$plusargs("PLAN=%s",name) || !$value$plusargs("CHECKS=%d",planned))`uvm_fatal("LAYER_CFG","missing plan")
      file=$fopen(name,"r");
      if(file==0)`uvm_fatal("LAYER_CFG","plan cannot be opened")
      while($fscanf(file,"%d %d %d %d %d %d %d %d %d",row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8])==9)begin
        if(row[0]==0)begin
          packet_item p=packet_item::type_id::create("packet");
          p.port=row[1][0];p.seq=row[2][6:0];p.gap=row[8];
          for(int i=0;i<row[3];i++)p.payload.push_back(row[4+i][7:0]);
          scenario.pool[p.port].push_back(p);
        end else foreach(row[k])scenario.steps.push_back(row[k]);
      end
      $fclose(file);
      if(scenario.steps.size()!=9*planned)`uvm_fatal("LAYER_CFG","plan length differs")
    endfunction
    function void connect_phase(uvm_phase phase);
      super.connect_phase(phase);
      driver.seq_item_port.connect(bus_sequencer.seq_item_export);
      driver.done.connect(scoreboard.driven);monitor.transfers.connect(scoreboard.observed);monitor.frames.connect(scoreboard.frame);
    endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      // Priorities are honoured only in a strict mode; the default mode ignores them.
      if(!ctl.arb_fifo)upper_sequencer.set_arbitration(UVM_SEQ_ARB_STRICT_FIFO);
      scenario.bus_sequencer=bus_sequencer;scenario.upper_sequencer=upper_sequencer;
      scenario.start(null);
      bus.recording=0;#1;phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if(!scoreboard.idle() || ctl.delivered!=ctl.sent || ctl.delivered<=0 || scoreboard.pairs<=0 || ctl.alarms<=0 ||
         scenario.pool[0].size()!=0 || scenario.pool[1].size()!=0 || driver.issued!=scoreboard.transfers)
        scoreboard.fail("LAYER_COUNTS","missing packets, pairs, alarms or unused plan");
      if(ctl.served_alarm!=ctl.alarms || ctl.served_done!=ctl.delivered)scoreboard.fail("LAYER_IRQ","interrupt causes and services differ");
    endfunction
    function void report_phase(uvm_phase phase);
      uvm_report_server server=uvm_report_server::get_server();super.report_phase(phase);
      if(server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)$fatal(1,"UVM report contains errors");
      $display("LAYER_COMPLETE steps=%0d transfers=%0d frames=%0d alarms=%0d served_done=%0d served_alarm=%0d services=%0d",
        planned,scoreboard.transfers,ctl.delivered,ctl.alarms,ctl.served_done,ctl.served_alarm,ctl.services);
      $display("RESULT PASS checks=%0d",planned);
    endfunction
  endclass
endpackage
