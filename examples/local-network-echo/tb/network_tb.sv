`timescale 1ns/1ps
module network_tb;
    parameter MAX_FRAME=128,MUTATION=0;
    reg clk=0,rst_n=0,rx_valid=0,rx_last=0,rx_error=0,tx_ready=0;
    reg [7:0] rx_data=0;wire tx_valid,tx_last;wire [7:0] tx_data;
    wire [1:0] occupancy;wire [31:0] accepted,full_drops,long_drops,rejected,transmitted;wire [3:0] last_drop;
    network_echo #(.MAX_FRAME(MAX_FRAME),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [7:0] expected[0:16383],rx_packet[0:MAX_FRAME+15],tx_packet[0:MAX_FRAME-1];
    reg [15:0] lengths[0:127];reg [31:0] v[0:5];
    reg held=0;reg [8:0] held_payload;
    reg [8*MAX_FRAME+16:0] held_head;
    reg head_hold=0;
    integer expected_rx,expected_tx,expected_bytes,expected_drops,planned_checks;
    integer fd,n,rx_frames=0,tx_frames=0,tx_bytes=0,rx_index=0,tx_index=0,resets=0,stall=0;
    reg [31:0] old_full=0,old_long=0,old_rejected=0;
    string vectors,expected_path,lengths_path,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"rx=%0d tx=%0d bytes=%0d",rx_frames,tx_frames,tx_bytes);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("EXPECTED=%s",expected_path) || !$value$plusargs("LENGTHS=%s",lengths_path) ||
           !$value$plusargs("WAVE=%s",wave) || !$value$plusargs("RX_FRAMES=%d",expected_rx) || !$value$plusargs("TX_FRAMES=%d",expected_tx) ||
           !$value$plusargs("TX_BYTES=%d",expected_bytes) || !$value$plusargs("DROPS=%d",expected_drops) || !$value$plusargs("CHECKS=%d",planned_checks))$fatal(1,"arguments required");
        if(expected_tx>128 || expected_bytes>16384)$fatal(1,"capacity exceeded");
        if(expected_tx>0)begin $readmemh(lengths_path,lengths,0,expected_tx-1);$readmemh(expected_path,expected,0,expected_bytes-1);end
        $dumpfile(wave);$dumpvars(2,network_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"stimulus missing");
        repeat(3)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5]);if(n!=6)$fatal(1,"bad stimulus row");
            if(!v[0][0] && rst_n)begin
                resets=resets+1;
                if(rx_index!=0)$display("COVER reset/receive");
                if(tx_valid || held)$display("COVER reset/transmit");
            end
            rst_n=v[0][0];rx_valid=v[1][0];rx_data=v[2][7:0];rx_last=v[3][0];rx_error=v[4][0];tx_ready=v[5][0];
            if(rst_n && tx_valid && stall<3)begin tx_ready=0;stall=stall+1;end
            #1;
            if(!rst_n)begin
                rx_frames=0;tx_frames=0;tx_bytes=0;rx_index=0;tx_index=0;held=0;head_hold=0;stall=0;
                old_full=0;old_long=0;old_rejected=0;
            end else begin
                if($isunknown({tx_valid,occupancy,accepted,full_drops,long_drops,rejected,transmitted}))fail("NET_UNKNOWN");
                if(held && (!tx_valid || {tx_last,tx_data}!==held_payload))fail("NET_HOLD");
                if(head_hold && (!dut.frame_valid || {dut.frame_error,dut.frame_length,dut.frame_data}!==held_head))fail("NET_QUEUE_HOLD");
                held=tx_valid && !tx_ready;held_payload={tx_last,tx_data};
                head_hold=dut.frame_valid && !dut.frame_ready;held_head={dut.frame_error,dut.frame_length,dut.frame_data};
                if(held)$display("COVER flow/tx-hold");
                if(rx_valid && held)$display("COVER flow/rx-unthrottled");
                if(occupancy==2)$display("COVER flow/full");
                if(full_drops!=old_full)$display("COVER drop/full");
                if(long_drops!=old_long)$display("COVER drop/oversize");
                if(rejected!=old_rejected)case(last_drop)
                    1:$display("COVER drop/crc");2:$display("COVER drop/length");3:$display("COVER drop/link");4:$display("COVER drop/filter");
                    5:$display("COVER drop/format");6:$display("COVER drop/ip-checksum");7:$display("COVER drop/udp-checksum");8:$display("COVER drop/unsupported");
                    default:fail("NET_DROP");
                endcase
                old_full=full_drops;old_long=long_drops;old_rejected=rejected;
                if(rx_valid)begin
                    if(rx_index<MAX_FRAME+16)rx_packet[rx_index]=rx_data;
                    rx_index=rx_index+1;
                    if(rx_last)begin
                        rx_frames=rx_frames+1;
                        if(rx_index>=42 && rx_packet[12]==8'h08 && rx_packet[13]==0 && rx_packet[40]==0 && rx_packet[41]==0)$display("COVER udp/zero-input");
                        rx_index=0;
                    end
                end
                if(tx_valid)begin
                    if(tx_frames>=expected_tx || tx_bytes>=expected_bytes)fail("NET_UNEXPECTED");
                    if(tx_data!==expected[tx_bytes] || tx_last!==(tx_index==int'(lengths[tx_frames])-1))fail("NET_FRAME");
                    if(tx_ready)begin
                        tx_packet[tx_index]=tx_data;tx_bytes=tx_bytes+1;tx_index=tx_index+1;
                        if(tx_last)begin
                            if(tx_index==64)$display("COVER frame/minimum");if(tx_index==MAX_FRAME)$display("COVER frame/maximum");
                            if(tx_packet[13]==8'h06)$display("COVER reply/arp");
                            else begin
                                $display("COVER reply/udp");
                                if(tx_packet[39][0])$display("COVER udp/odd");
                                if({tx_packet[38],tx_packet[39]}==8)$display("COVER udp/empty");
                                if({tx_packet[40],tx_packet[41]}==16'hffff)$display("COVER udp/ffff-checksum");
                            end
                            tx_frames=tx_frames+1;tx_index=0;
                        end
                    end
                end
            end
            @(posedge clk);#1;@(negedge clk);
        end
        if(rx_frames!=expected_rx || tx_frames!=expected_tx || tx_bytes!=expected_bytes || tx_index!=0 || rx_index!=0 || tx_valid || occupancy!=0 ||
           full_drops+long_drops+rejected!=expected_drops || accepted!=transmitted+rejected || transmitted!=expected_tx)fail("NET_COMPLETION");
        $display("COUNT rx_frames=%0d",rx_frames);$display("COUNT tx_frames=%0d",tx_frames);$display("COUNT tx_bytes=%0d",tx_bytes);
        $display("COUNT drops=%0d",full_drops+long_drops+rejected);$display("COUNT resets=%0d",resets);
        if(planned_checks!=1+tx_bytes)fail("NET_COMPLETION");
        $display("RESULT PASS checks=%0d",planned_checks);$fclose(fd);$finish;
    end
endmodule
