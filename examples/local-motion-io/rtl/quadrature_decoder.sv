// Two sampling FFs followed by FILTER equal samples. Positive: 00,01,11,10.
module quadrature_decoder #(parameter FILTER=2,MUTATION=0)(
    input wire clk,rst_n,a,b,origin_en,input wire signed [15:0] origin,
    output reg signed [15:0] position,output reg step,invalid,wrapped,
    output reg [31:0] invalid_count
);
    reg [1:0] sync1,sync2,candidate,filtered,previous;
    reg [31:0] stable;
    reg [1:0] next_filtered;
    reg signed [1:0] delta;
    always @*begin
        next_filtered=filtered;
        if(candidate==sync2 && stable>=FILTER-1)next_filtered=sync2;
        else if(candidate!=sync2 && FILTER==1)next_filtered=sync2;
        delta=0;
        case({previous,next_filtered})
            4'b0001,4'b0111,4'b1110,4'b1000:delta=1;
            4'b0010,4'b1011,4'b1101,4'b0100:delta=-1;
            default:delta=0;
        endcase
        if(MUTATION==2)delta=-delta;
    end
    always @(posedge clk)begin
        if(!rst_n)begin sync1<=0;sync2<=0;candidate<=0;filtered<=0;previous<=0;stable<=0;position<=0;step<=0;invalid<=0;wrapped<=0;invalid_count<=0;end
        else begin
            sync1<={a,b};sync2<=sync1;
            if(candidate!=sync2)begin candidate<=sync2;stable<=1;end else if(stable<FILTER)stable<=stable+1'b1;
            filtered<=next_filtered;previous<=next_filtered;
            step<=0;invalid<=0;wrapped<=0;
            if(origin_en)position<=origin;
            else if(previous!=next_filtered)begin
                if(delta==0)begin invalid<=MUTATION!=4;invalid_count<=invalid_count+1'b1;end
                else begin
                    step<=1;
                    if(delta==1)begin position<=position+16'sd1;wrapped<=position==16'sh7fff;end
                    else begin position<=position-16'sd1;wrapped<=position==16'sh8000;end
                end
            end
        end
    end
endmodule
