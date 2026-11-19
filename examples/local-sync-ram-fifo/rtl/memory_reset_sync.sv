module memory_reset_sync(input wire clk, arst_n, output wire up);
    (* ASYNC_REG="TRUE" *) reg [1:0] release_pipe;
    always @(posedge clk or negedge arst_n)
        if(!arst_n)release_pipe<=0;else release_pipe<={release_pipe[0],1'b1};
    assign up=release_pipe[1];
endmodule
