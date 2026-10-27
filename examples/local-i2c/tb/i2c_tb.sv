`timescale 1ns/1ps
module i2c_tb;
    parameter HALF_DIV=8,MUTATION=0;
    reg clk=0;always #5 clk=!clk;
    reg rst_n=0,reject_data=0,master_scl_low=0,master_sda_low=0;
    reg [7:0] stretch_cycles=0;
    tri1 scl,sda;
    assign scl=master_scl_low ? 1'b0 : 1'bz;
    assign sda=master_sda_low ? 1'b0 : 1'bz;
    wire [7:0] value;
    i2c_target #(.MUTATION(MUTATION)) dut(clk,rst_n,reject_data,stretch_cycles,scl,sda,value);
    integer fd,rc,mode,address,data,stretch,before_value,after_value,checks=0;
    integer writes=0,reads=0,target_nacks=0,resets=0,stretches=0,last_ack_wait=0;
    reg sampled,recovering=0;
    reg [7:0] observed;
    string vectors,wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"command=%0d mode=%0d value=%h scl=%b sda=%b",checks,mode,value,scl,sda);end
    endtask
    task ticks(input integer n);repeat(n) @(negedge clk);endtask
    task wait_high(output integer waited);
        begin
            #1;waited=0; // Let the open-drain net resolve after controller release.
            while(scl!==1'b1 && waited<100) begin ticks(1);waited=waited+1;end
            if(scl!==1'b1) fail("I2C_TIMEOUT");
        end
    endtask
    task bus_start;
        integer waited;
        begin
            master_scl_low=1;master_sda_low=0;ticks(HALF_DIV);
            master_scl_low=0;wait_high(waited);ticks(HALF_DIV);
            if(sda!==1) fail("I2C_START");
            master_sda_low=1;ticks(HALF_DIV);master_scl_low=1;
        end
    endtask
    task bus_stop;
        integer waited;
        begin
            master_scl_low=1;master_sda_low=1;ticks(HALF_DIV);
            master_scl_low=0;wait_high(waited);ticks(HALF_DIV);
            master_sda_low=0;ticks(HALF_DIV);
            if(sda!==1 || scl!==1) fail("I2C_STOP");
            $display("COVER bus/stop");
        end
    endtask
    task bit_io(input bit drive_bit,input bit is_ack,output reg result_bit);
        integer waited;
        begin
            master_scl_low=1;master_sda_low=!drive_bit;ticks(HALF_DIV);
            master_scl_low=0;wait_high(waited);
            if(is_ack) begin
                last_ack_wait=waited;
                if(waited>0) begin stretches=stretches+1;$display("COVER bus/stretch");end
            end else if(waited>0) fail("I2C_STRETCH");
            ticks(HALF_DIV/2);result_bit=sda;ticks(HALF_DIV-HALF_DIV/2);
            if(result_bit!==0 && result_bit!==1) fail("I2C_UNKNOWN");
            master_scl_low=1;
        end
    endtask
    task send_byte(input reg [7:0] byte_value,input bit want_ack);
        begin
            for(integer i=7;i>=0;i=i-1) bit_io(byte_value[i],0,sampled);
            bit_io(1,1,sampled);
            if(sampled!==!want_ack) fail("I2C_ACK");
            if((last_ack_wait>0)!==(want_ack && stretch_cycles!=0)) fail("I2C_STRETCH");
            if(want_ack && stretch_cycles!=0 &&
               (last_ack_wait<stretch_cycles-HALF_DIV || last_ack_wait>stretch_cycles+4-HALF_DIV)) fail("I2C_STRETCH");
            if(want_ack) $display("COVER response/ack");
            else begin target_nacks=target_nacks+1;$display("COVER response/nack");end
        end
    endtask
    task receive_byte(input reg [7:0] expected_byte);
        begin
            observed=0;
            for(integer i=7;i>=0;i=i-1) begin bit_io(1,0,sampled);observed[i]=sampled;end
            if(observed!==expected_byte) fail("I2C_DATA");
            bit_io(1,0,sampled); // Controller NACK terminates the one-byte read.
            reads=reads+1;$display("COVER transfer/read");$display("COVER response/controller-nack");
        end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,i2c_tb);end
        ticks(4);rst_n=1;ticks(4);
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot open vectors");
        while(!$feof(fd)) begin
            rc=$fscanf(fd,"%h %h %h %h %h %h\n",mode,address,data,stretch,before_value,after_value);
            if(rc!=6) $fatal(1,"malformed vector");
            if(value!==before_value[7:0]) fail("I2C_DATA");
            stretch_cycles=stretch;reject_data=mode==4;
            bus_start();$display("COVER bus/start");
            send_byte((address<<1)|(mode==2),mode!=3);
            if(mode==2) receive_byte(before_value);
            else if(mode==5) begin
                for(integer i=7;i>=4;i=i-1) bit_io((data>>i)&1,0,sampled);
                rst_n=0;master_scl_low=0;master_sda_low=0;ticks(4);
                if(scl!==1 || sda!==1 || value!==0) fail("I2C_RESET");
                rst_n=1;ticks(HALF_DIV);resets=resets+1;recovering=1;
                $display("COVER reset/active");
            end else if(mode!=3) begin
                send_byte(data,mode!=4);
                if(mode!=4) begin writes=writes+1;$display("COVER transfer/write");end
                else $display("COVER response/data-reject");
                if(mode==1) begin
                    bus_start();$display("COVER bus/repeated-start");
                    send_byte((address<<1)|1,1);receive_byte(after_value);
                end
            end else $display("COVER address/mismatch");
            if(mode!=5) bus_stop();
            ticks(4);
            if(value!==after_value[7:0]) fail("I2C_DATA");
            if(mode==1) begin
                if(after_value==0) $display("COVER data/zero");
                if(after_value==255) $display("COVER data/ones");
                if(after_value==85) $display("COVER data/alternating");
                if(after_value==1) $display("COVER data/lsb");
                if(after_value==128) $display("COVER data/msb");
                if(recovering) begin $display("COVER reset/recovery");recovering=0;end
            end
            checks=checks+1;
        end
        $fclose(fd);
        $display("COUNT writes=%0d",writes);$display("COUNT reads=%0d",reads);
        $display("COUNT target_nacks=%0d",target_nacks);$display("COUNT resets=%0d",resets);
        $display("COUNT stretches=%0d",stretches);
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
