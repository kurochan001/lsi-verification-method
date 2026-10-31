// Self-composition: public inputs are shared; secret inputs vary independently.
module compare_formal #(parameter integer BYTES=2,MUTATION=0) (
    input wire clk,rst_n,start,result_ready,
    input wire [8*BYTES-1:0] secret0,secret1,guess
);
    wire ready0,ready1,busy0,busy1,valid0,valid1,match0,match1;
    wire [2:0] status0,status1;
    constant_time_compare #(.BYTES(BYTES),.MUTATION(MUTATION)) a(
        .clk(clk),.rst_n(rst_n),.start(start),.result_ready(result_ready),.secret(secret0),.guess(guess),
        .ready(ready0),.busy(busy0),.result_valid(valid0),.match(match0),.public_status(status0));
    constant_time_compare #(.BYTES(BYTES),.MUTATION(MUTATION)) b(
        .clk(clk),.rst_n(rst_n),.start(start),.result_ready(result_ready),.secret(secret1),.guess(guess),
        .ready(ready1),.busy(busy1),.result_valid(valid1),.match(match1),.public_status(status1));
    reg past_valid=0;always @(posedge clk)past_valid<=1;
    reg expected0,expected1,valid,first_diff,last_diff;
    reg [$clog2(BYTES+1)-1:0] remaining;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin remaining<=0;valid<=0;expected0<=0;expected1<=0;first_diff<=0;last_diff<=0;end
        else begin
            if(valid && result_ready)valid<=0;
            if(remaining>0)begin
                remaining<=remaining-1;
                if(remaining==1)valid<=1;
            end
            if(start && remaining==0 && !valid)begin
                remaining<=BYTES;expected0<=secret0==guess;expected1<=secret1==guess;
                first_diff<=secret0[7:0]!=guess[7:0];
                last_diff<=secret0[8*BYTES-1:8*BYTES-8]!=guess[8*BYTES-1:8*BYTES-8] &&
                    secret0[8*BYTES-9:0]==guess[8*BYTES-9:0];
            end
        end
    end
    always @(posedge clk)begin
        if(!past_valid)as_initial_reset: assume(!rst_n);
        if(past_valid)begin
            ai_model_bounds: assert(remaining<=BYTES);
            ap_timing: assert({ready0,busy0,valid0}=={ready1,busy1,valid1} &&
                              busy0==(remaining>0) && valid0==valid);
            ap_public: assert(status0==status1);
            if(valid0)ap_result: assert(match0==expected0 && match1==expected1);
            if(rst_n && $past(rst_n && valid0 && !result_ready))
                ap_hold: assert(valid0 && $stable(match0) && $stable(match1));
            cp_match: cover(valid0 && match0);
            cp_mismatch: cover(valid0 && !match0);
            cp_different_secrets: cover(valid0 && match0!=match1);
            cp_first_byte: cover(valid0 && first_diff);
            cp_last_byte: cover(valid0 && last_diff);
            cp_backpressure: cover(valid0 && $past(valid0) && !result_ready);
            cp_reset_busy: cover($past(busy0) && !rst_n);
        end
    end
endmodule
