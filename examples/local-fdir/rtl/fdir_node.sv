// Educational instrument controller, not an airborne/space-qualified implementation.
// One command slot; effects occur only at commit. Fault entry cancels a pending command.
module fdir_node #(parameter DEPTH=4,WD_LIMIT=5,TRIP=3,MUTATION=0)(
    input wire clk,rst_n,start,kick,ack,recover,scrub_en,cfg_write,
    input wire [7:0] cfg_data,fault0,fault1,fault2,
    input wire inject_en,input wire [$clog2(DEPTH)-1:0] inject_addr,input wire [12:0] inject_mask,
    input wire maint_write,input wire [$clog2(DEPTH)-1:0] maint_addr,input wire [7:0] maint_data,
    input wire cmd_valid,input wire [1:0] cmd_op,input wire [$clog2(DEPTH)-1:0] cmd_addr,input wire [7:0] cmd_data,cmd_seq,
    output wire cmd_ready,output wire [7:0] actuator,
    output reg commit,cancelled,recovered,recovery_failed,output reg [7:0] result,
    output reg [1:0] state,output reg [3:0] cause,output reg irq,output reg [7:0] expected_seq
);
    localparam OFF=0,RUN=1,SAFE=2,CHECK=3;
    reg pending;reg [1:0] operation;reg [$clog2(DEPTH)-1:0] address,scan;
    reg [7:0] payload,actuator_value;
    integer streak;
    wire [7:0] limit_value;wire mismatch,repair_attempt;
    tmr_register #(.WIDTH(8)) config_bank(.clk(clk),.rst_n(rst_n),.write_en(cfg_write && (state==OFF || state==SAFE)),.repair_en(scrub_en),
        .write_data(cfg_data),.fault0(fault0),.fault1(fault1),.fault2(fault2),.voted(limit_value),.disagreement(mismatch),.repair_attempt(repair_attempt));
    wire mem_corrected,mem_uncorrectable,scrub_corrected,scrub_uncorrectable;
    wire [7:0] mem_data;
    wire [$clog2(DEPTH)-1:0] scrub_addr;
    wire [3:0] timer_count,watchdog_count;
    wire timer_irq,watchdog_request,timer_expired;
    wire finishing=state==CHECK && !mismatch && !mem_uncorrectable && int'(scan)==DEPTH-1;
    wire load_watchdog=(state==OFF && start)||finishing;
    timer_watchdog #(.WIDTH(4)) watchdog(.clk(clk),.rst_n(rst_n),.timer_enable(1'b0),.periodic(1'b0),.timer_load(1'b0),.timer_reload(4'd0),
        .watchdog_enable(state==RUN),.watchdog_load(load_watchdog),.watchdog_reload(4'(WD_LIMIT)),.kick(kick),.clear_irq(1'b0),
        .timer_count(timer_count),.watchdog_count(watchdog_count),.irq(timer_irq),.watchdog_reset_request(watchdog_request),.timer_expired(timer_expired));
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_timer=&{1'b0,timer_count,timer_irq,watchdog_request,timer_expired,repair_attempt,scrub_addr,mem_corrected,scrub_corrected};
    /* verilator lint_on UNUSEDSIGNAL */
    wire [3:0] pre_fault={1'b0,(watchdog_count==1 && !kick),scrub_uncorrectable||(pending && operation==1 && mem_uncorrectable),mismatch && streak>=TRIP-1};
    assign cmd_ready=rst_n && state==RUN && !pending && pre_fault==0;
    wire accepted=cmd_valid && cmd_ready;
    wire bad_command=accepted && (cmd_op>1 || cmd_seq!=expected_seq);
    wire [3:0] event_cause=state==RUN ? pre_fault|{bad_command,3'd0} : 4'd0;
    wire fatal=event_cause!=0;
    wire reading=state==CHECK || (state==RUN && pending && operation==1);
    wire writing=(state==RUN && pending && operation==0 && !fatal) || (state==SAFE && maint_write);
    wire [$clog2(DEPTH)-1:0] mem_addr=state==CHECK ? scan : state==SAFE ? maint_addr : address;
    protected_store #(.DEPTH(DEPTH)) store(.clk(clk),.rst_n(rst_n),.write_en(writing),.read_en(reading),.scrub_en(scrub_en && state!=CHECK),
        .addr(mem_addr),.write_data(state==SAFE ? maint_data:payload),.inject_en(inject_en),.inject_addr(inject_addr),.inject_mask(inject_mask),
        .read_data(mem_data),.corrected(mem_corrected),.uncorrectable(mem_uncorrectable),.scrub_addr(scrub_addr),.scrub_corrected(scrub_corrected),.scrub_uncorrectable(scrub_uncorrectable));
    assign actuator=rst_n && state==RUN ? actuator_value : 8'd0;
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=OFF;cause<=0;irq<=0;expected_seq<=0;commit<=0;cancelled<=0;recovered<=0;recovery_failed<=0;result<=0;
            pending<=0;operation<=0;address<=0;payload<=0;actuator_value<=0;scan<=0;streak<=0;
        end else begin
            commit<=0;cancelled<=0;recovered<=0;recovery_failed<=0;
            if(ack)irq<=0;
            if(mismatch && state==RUN)begin if(streak<TRIP)streak<=streak+1;end else streak<=0;
            case(state)
                OFF:if(start)state<=RUN;
                RUN:begin
                    if(fatal)begin
                        state<=SAFE;cause<=cause|event_cause;irq<=1;actuator_value<=0;cancelled<=pending;pending<=0;
                        if(MUTATION==1 && pending)begin commit<=1;result<=mem_data;end
                    end else if(pending)begin
                        pending<=0;commit<=1;result<=operation==0 ? payload : mem_data>limit_value ? limit_value : mem_data;
                        if(operation==1)actuator_value<=mem_data>limit_value ? limit_value : mem_data;
                        expected_seq<=expected_seq+1'b1;
                    end else if(accepted)begin pending<=1;operation<=cmd_op;address<=cmd_addr;payload<=cmd_data;end
                end
                SAFE:if((recover || (MUTATION==4 && ack)) && (!mismatch || MUTATION==4))begin state<=CHECK;scan<=0;end
                CHECK:begin
                    if((mismatch || mem_uncorrectable) && MUTATION!=2)begin state<=SAFE;cause<=cause|{2'd0,mem_uncorrectable,mismatch};irq<=1;recovery_failed<=1;end
                    else if(int'(scan)==DEPTH-1)begin state<=RUN;cause<=0;irq<=0;recovered<=1;actuator_value<=0;end
                    else scan<=scan+1'b1;
                end
                default:state<=OFF;
            endcase
            if(MUTATION==3 && ack)irq<=0;
        end
    end
endmodule
