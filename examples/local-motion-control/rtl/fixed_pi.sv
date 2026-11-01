// Q4 gains; symmetric nearest rounding, ties away from zero.
// Candidate integration is rejected when it pushes an already excessive output further out.
module fixed_pi #(parameter LIMIT=8,LATENCY=3,KP=8,KI=1,MUTATION=0)(
    input wire clk,rst_n,clear,start,hold,input wire signed [16:0] error_in,
    output reg busy,done,clipped,antiwindup,output reg signed [7:0] effort,
    output reg signed [31:0] integral
);
    reg signed [16:0] saved_error;
    reg [31:0] remaining;
    reg signed [31:0] candidate,numerator,rounded;
    reg freeze_i;
    always @*begin
        candidate=integral+32'(saved_error)*KI;
        if(candidate>LIMIT*16)candidate=LIMIT*16;
        if(candidate<-(LIMIT*16))candidate=-(LIMIT*16);
        numerator=32'(saved_error)*KP+candidate;
        freeze_i=(numerator>LIMIT*16 && saved_error>0)||(numerator<-(LIMIT*16) && saved_error<0);
        if(freeze_i && MUTATION!=1)candidate=integral;
        numerator=32'(saved_error)*KP+candidate;
        rounded=numerator>=0 ? (numerator+8)/16 : -((-numerator+8)/16);
    end
    always @(posedge clk)begin
        if(!rst_n || clear)begin busy<=0;done<=0;clipped<=0;antiwindup<=0;effort<=0;integral<=0;saved_error<=0;remaining<=0;end
        else begin
            done<=0;
            if(start && !busy)begin busy<=1;saved_error<=error_in;remaining<=LATENCY-1;end
            else if(busy && !hold)begin
                if(remaining!=0)remaining<=remaining-1'b1;
                else begin
                    busy<=0;done<=1;integral<=candidate;antiwindup<=freeze_i;
                    clipped<=rounded>LIMIT || rounded< -LIMIT;
                    effort<=8'(rounded>LIMIT ? LIMIT : rounded< -LIMIT ? -LIMIT:rounded);
                end
            end
        end
    end
endmodule
