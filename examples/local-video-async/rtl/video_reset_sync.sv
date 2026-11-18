// Asynchronous assertion, two-edge local synchronous release.
module video_reset_sync(input wire clk,arst_n,output wire reset_n);
    (* ASYNC_REG = "TRUE" *) reg first_stage,second_stage;
    always @(posedge clk or negedge arst_n)
        if (!arst_n) begin first_stage<=0;second_stage<=0;end
        else begin first_stage<=1;second_stage<=first_stage;end
    assign reset_n=second_stage;
endmodule
