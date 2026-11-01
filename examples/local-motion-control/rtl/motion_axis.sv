// One-axis teaching controller. Plant and power electronics are outside this RTL.
module motion_axis #(parameter PERIOD=16,DEAD=2,FILTER=2,SAMPLE=64,LATENCY=3,SPEED_LIMIT=6,MUTATION=0)(
    input wire clk,rst_n,arm,disarm,ack,estop,encoder_a,encoder_b,compute_hold,origin_en,
    input wire signed [15:0] target,origin,
    output wire pwm_hi,pwm_lo,output reg armed,irq,updated,cancelled,sampled,
    output reg [5:0] cause,output wire signed [15:0] position,
    output wire signed [7:0] effort
);
    wire enc_step,enc_invalid,enc_wrapped;wire [31:0] enc_errors;
    quadrature_decoder #(.FILTER(FILTER)) encoder(.clk(clk),.rst_n(rst_n),.a(encoder_a),.b(encoder_b),.origin_en(origin_en && !armed),.origin(origin),
        .position(position),.step(enc_step),.invalid(enc_invalid),.wrapped(enc_wrapped),.invalid_count(enc_errors));
    reg [31:0] sample_phase,stalled;
    reg signed [15:0] last_position;
    wire tick=armed && sample_phase==SAMPLE-1;
    wire busy,done,clipped,antiwindup;
    wire signed [31:0] integral;
    wire signed [15:0] velocity=position-last_position;
    wire moving_command=effort>=3 || effort<=-3;
    wire [5:0] event_cause={armed && enc_wrapped,armed && tick && (32'(velocity)>SPEED_LIMIT || 32'(velocity)< -SPEED_LIMIT),
        armed && moving_command && !enc_step && stalled>=3*SAMPLE-1,armed && tick && busy && MUTATION!=3,armed && enc_invalid,estop};
    wire fault=event_cause!=0;
    wire enabled=armed && !fault && !disarm;
    wire signed [16:0] error_in={target[15],target}-{position[15],position};
    fixed_pi #(.LIMIT(PERIOD/2),.LATENCY(LATENCY),.MUTATION(MUTATION==1 ? 1:0)) controller(.clk(clk),.rst_n(rst_n),.clear(!enabled),
        .start(tick && !fault && !disarm),.hold(compute_hold),.error_in(error_in),.busy(busy),.done(done),.clipped(clipped),.antiwindup(antiwindup),.effort(effort),.integral(integral));
    wire boundary,config_error;wire [31:0] phase,active_duty,shadow_duty;
    safe_pwm #(.PERIOD(PERIOD),.DEAD(DEAD),.MUTATION(MUTATION==2 ? 1:0)) pwm(.clk(clk),.rst_n(rst_n),.enable(enabled),.stop(estop),
        .load((done && enabled)||!enabled),.duty_in(enabled ? 32'(PERIOD/2)+32'(effort) : 32'(PERIOD/2)),.hi(pwm_hi),.lo(pwm_lo),.boundary(boundary),.config_error(config_error),
        .phase(phase),.active_duty(active_duty),.shadow_duty(shadow_duty));
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_observation=&{1'b0,enc_errors,clipped,antiwindup,integral,boundary,config_error,phase,active_duty,shadow_duty};
    /* verilator lint_on UNUSEDSIGNAL */
    always @(posedge clk)begin
        if(!rst_n)begin armed<=0;irq<=0;cause<=0;sample_phase<=0;stalled<=0;last_position<=0;updated<=0;cancelled<=0;sampled<=0;end
        else begin
            updated<=0;cancelled<=0;sampled<=0;
            if(ack)irq<=0;
            if(!armed)begin sample_phase<=0;stalled<=0;end
            else begin
                sample_phase<=tick ? 0:sample_phase+1'b1;
                if(!moving_command || enc_step)stalled<=0;else if(stalled<3*SAMPLE)stalled<=stalled+1'b1;
            end
            if(fault)begin armed<=0;cause<=cause|event_cause;irq<=1;cancelled<=busy||done;sample_phase<=0;stalled<=0;end
            else if(disarm)begin armed<=0;cancelled<=busy||done;sample_phase<=0;stalled<=0;end
            else if(arm && !armed && !enc_invalid && !enc_wrapped)begin armed<=1;cause<=0;irq<=0;sample_phase<=0;stalled<=0;last_position<=origin_en ? origin:position;end
            else if(armed)begin
                if(tick)begin last_position<=position;sampled<=!busy;end
                if(done)updated<=1;
            end
            if(MUTATION==4 && arm && estop)begin armed<=1;cause<=0;end
        end
    end
endmodule
