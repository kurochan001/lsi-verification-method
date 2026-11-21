`timescale 1ns/1ps
// Block-level: a W1C write and the last B response on the same clock edge, which firmware cannot place.
module dma_status_tb;
    parameter W=5,H=5;
    localparam N=W*H;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,psel=0,penable=0,pwrite=0;reg [7:0] paddr=0;reg [31:0] pwdata=0;
    wire pready,pslverr,irq,arvalid,rready,awvalid,wvalid,wlast,bready,busy,done,error;
    wire [31:0] prdata,araddr,awaddr,wdata;wire [7:0] arlen,awlen;wire [2:0] arsize,awsize;wire [1:0] arburst,arid,awburst,awid;wire [3:0] wstrb;
    reg arready=1,awready=1,wready=1,rvalid=0,rlast=0,bvalid=0;reg [31:0] rdata=0;reg [1:0] rid=0,rresp=0,bid=0,bresp=0;
    image_dma #(.W(W),.H(H)) dut(.*);
    integer bad_response,bid_at=-1,extra_r=0,read_left=0,written=0,received=0,responses=0;
    wire expect_error=bad_response!=0 || bid_at>=0 || extra_r!=0;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"at %0t",$time);end endtask
    task apb(input [7:0] address,input [31:0] value);
        begin
            psel=1;penable=0;pwrite=1;paddr=address;pwdata=value;@(negedge clk);
            penable=1;@(negedge clk);psel=0;penable=0;pwrite=0;
        end
    endtask
    // Reads return zeros at full speed; the bench decides when each B response is offered.
    always @(posedge clk)begin
        if(arvalid && arready)read_left<=int'(arlen)+1;
        else if(rvalid && rready)read_left<=read_left-1;
        if(wvalid && wready)written<=written+1;
        if(rvalid && rready)received<=received+1;
    end
    // EXTRA_R offers one more R beat after the last requested one, with ID, response and RLAST that look
    // valid, so only the beat count can report it.
    always @(negedge clk)begin
        rvalid<=read_left>0 || (extra_r!=0 && received==N);rlast<=read_left==1 || (read_left==0 && extra_r!=0 && received==N);
    end
    task frame(input [1:0] response,input bit w1c);
        begin
            apb(0,1);if(!busy)fail("DMA_NOT_STARTED");
            forever begin
                @(negedge clk);
                if(bready)begin
                    if(written==N)begin
                        // The access phase of a W1C meets the completion edge.
                        bvalid=1;bresp=response;bid=bid_at==99 ? 2'd1:2'd0;
                        if(w1c)begin psel=1;penable=1;pwrite=1;paddr=4;pwdata=6;end
                        #1;if(w1c && !pready)fail("DMA_W1C_NOT_READY");
                        @(negedge clk);bvalid=0;bresp=0;bid=0;psel=0;penable=0;pwrite=0;break;
                    end
                    // BID_AT names the B response that carries a wrong ID; 99 is the last one of the frame.
                    bvalid=1;bid=responses==bid_at ? 2'd1:2'd0;@(negedge clk);bvalid=0;bid=0;responses=responses+1;
                end
            end
            written=0;received=0;responses=0;
        end
    endtask
    initial begin
        if(!$value$plusargs("BRESP=%d",bad_response))$fatal(1,"arguments required");
        if(!$value$plusargs("BID_AT=%d",bid_at))bid_at=-1;
        if(!$value$plusargs("EXTRA_R=%d",extra_r))extra_r=0;
        repeat(2)@(negedge clk);rst_n=1;@(negedge clk);apb(16,1);
        // The completion wins over the W1C on the same edge, and the IRQ rises for it.
        frame(2'(bad_response),1);
        if(busy || done!==!expect_error || error!==expect_error)fail("DMA_STATUS_LOST");
        if(!irq)fail("DMA_IRQ_LOST");
        // A W1C on any later edge still clears the event.
        apb(4,6);if(done || error || irq)fail("DMA_W1C_IGNORED");
        // Completing without the collision gives the same status.
        frame(2'(bad_response),0);
        if(busy || done!==!expect_error || error!==expect_error)fail("DMA_STATUS_LOST");
        $display("RESULT PASS checks=1");$finish;
    end
    initial begin #2000000;fail("DMA_TIMEOUT");end
endmodule
