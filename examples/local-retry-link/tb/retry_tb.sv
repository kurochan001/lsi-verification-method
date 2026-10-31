`timescale 1ns/1ps
module retry_tb;
    parameter TIMEOUT=3,RETRIES=2,MUTATION=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,s_valid=0,wire_ready=0,drop_data=0,corrupt_data=0,drop_ack=0,corrupt_ack=0,m_ready=0,done_ready=0;
    reg [3:0] injected_ack=0;
    reg [7:0] s_data=0;
    wire s_ready,wire_valid,m_valid,done_valid,error,failed,rx_ack_valid;
    wire [7:0] m_data;wire [16:0] wire_word;wire [3:0] rx_ack;
    wire ack_valid=(injected_ack!=0) || (rx_ack_valid && !drop_ack);
    wire [3:0] ack=injected_ack!=0 ? injected_ack : rx_ack^(corrupt_ack ? 4'h1 : 4'h0);
    wire [16:0] incoming=wire_word^(corrupt_data ? 17'h100 : 17'h0);
    retry_sender #(.TIMEOUT(TIMEOUT),.RETRIES(RETRIES),.MUTATION(MUTATION)) sender(.*);
    retry_receiver #(.MUTATION(MUTATION)) receiver(.clk(clk),.rst_n(rst_n),.wire_valid(wire_valid && wire_ready && !drop_data),
        .wire_word(incoming),.m_ready(m_ready),.m_valid(m_valid),.m_data(m_data),.ack_valid(rx_ack_valid),.ack(rx_ack));
    integer fd,n,checks=0,inputs=0,outputs=0,successes=0,failures=0,retries=0;
    reg [63:0] v[0:18];string vectors,wave;reg sent=0,delivered=0,pending=0;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,retry_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18]);if(n!=19)$fatal(1,"bad row");
            rst_n=v[0][0];s_valid=v[1][0];s_data=v[2][7:0];wire_ready=v[3][0];drop_data=v[4][0];corrupt_data=v[5][0];drop_ack=v[6][0];corrupt_ack=v[7][0];injected_ack=v[8][3:0];m_ready=v[9][0];done_ready=v[10][0];#1;
            if(s_ready!==v[11][0] || wire_valid!==v[12][0] || done_valid!==v[16][0] || failed!==v[18][0])fail("LINK_TX");
            if(wire_valid && wire_word!==v[13][16:0])fail("LINK_TX");
            if(done_valid && error!==v[17][0])fail("LINK_TX");
            if(m_valid!==v[14][0] || (m_valid && m_data!==v[15][7:0]))fail("LINK_RX");
            if(!rst_n)begin if(pending)$display("COVER reset/pending");sent=0;delivered=0;pending=0;end
            else begin
                if(s_valid && s_ready)begin inputs=inputs+1;sent=0;delivered=0;pending=1;$display("COVER input/accepted");end
                if(s_valid && failed)$display("COVER failure/blocks-new-input");
                if(wire_valid && !wire_ready)$display("COVER wire/backpressure");
                if(wire_valid && wire_ready)begin
                    if(sent)begin retries=retries+1;$display("COVER retry/sent");end
                    sent=1;
                    if(drop_data)$display("COVER fault/data-drop");
                    if(corrupt_data)$display("COVER fault/data-corrupt");
                    if(!drop_data && !corrupt_data && incoming[16]!=receiver.expected_seq)$display("COVER receive/duplicate");
                    if(!drop_data && !corrupt_data && incoming[16]==receiver.expected_seq && m_valid && !m_ready)$display("COVER receive/full-reject");
                    if(incoming[16])$display("COVER sequence/one");else $display("COVER sequence/zero");
                end
                if(rx_ack_valid && drop_ack)$display("COVER fault/ack-drop");
                if(rx_ack_valid && corrupt_ack)$display("COVER fault/ack-corrupt");
                if(injected_ack!=0 && sender.state==2)$display("COVER ack/old-sequence");
                if(m_valid && !m_ready)$display("COVER output/hold");
                if(m_valid && m_ready)begin outputs=outputs+1;delivered=1;$display("COVER output/delivered");end
                if(done_valid && !done_ready)$display("COVER result/hold");
                if(done_valid && done_ready)begin
                    pending=0;
                    if(error)begin
                        failures=failures+1;
                        if(delivered)$display("COVER failure/already-delivered");else $display("COVER failure/not-delivered");
                    end else begin successes=successes+1;$display("COVER result/success");end
                end
            end
            @(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        $display("COUNT steps=%0d",checks);$display("COUNT inputs=%0d",inputs);$display("COUNT outputs=%0d",outputs);
        $display("COUNT successes=%0d",successes);$display("COUNT failures=%0d",failures);$display("COUNT retries=%0d",retries);
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
