// Complementary bipolar PWM. Outputs select positive/negative bridge states.
// Config writes latch at the next carrier boundary, including a same-edge write.
module safe_pwm #(parameter PERIOD=16,DEAD=2,MUTATION=0)(
    input wire clk,rst_n,enable,stop,load,input wire [31:0] duty_in,
    output wire hi,lo,output reg boundary,config_error,
    output reg [31:0] phase,active_duty,shadow_duty
);
    reg running,target;
    reg [1:0] drive;
    reg [31:0] gap;
    wire accepted=load && duty_in<=PERIOD;
    wire edge_start=enable && (!running || phase==PERIOD-1);
    wire [31:0] next_phase=!running || phase==PERIOD-1 ? 32'd0:phase+1'b1;
    wire [31:0] next_duty=edge_start ? (accepted ? duty_in:shadow_duty):active_duty;
    wire want=next_phase<next_duty;
    assign hi=rst_n && enable && !stop && (drive==1 || MUTATION==1);
    assign lo=rst_n && enable && !stop && (drive==2 || MUTATION==1);
    always @(posedge clk)begin
        if(!rst_n)begin phase<=PERIOD-1;active_duty<=PERIOD/2;shadow_duty<=PERIOD/2;running<=0;drive<=0;gap<=DEAD-1;target<=0;boundary<=0;config_error<=0;end
        else begin
            boundary<=0;config_error<=load && !accepted;
            if(accepted)shadow_duty<=duty_in;
            if(MUTATION==3 && accepted)active_duty<=duty_in;
            if(!enable || stop)begin running<=0;drive<=0;phase<=PERIOD-1;gap<=DEAD-1;end
            else begin
                running<=1;phase<=next_phase;
                if(edge_start)begin active_duty<=next_duty;boundary<=1;end
                if(!running || target!=want)begin drive<=0;target<=want;gap<=DEAD-1;end
                else if(gap!=0)begin gap<=gap-1'b1;drive<=0;end
                else drive<=want ? 2'd1:2'd2;
                if(MUTATION==5)begin target<=want;gap<=0;drive<=want ? 2'd1:2'd2;end
            end
        end
    end
endmodule
