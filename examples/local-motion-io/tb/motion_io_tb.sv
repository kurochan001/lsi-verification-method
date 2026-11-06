`timescale 1ns/1ps
module motion_io_tb;
    parameter PERIOD=16,DEAD=2,FILTER=2,MUTATION=0;
    reg clk=0,rst_n=0,enable=0,stop=0,load=0,origin_en=0;reg [31:0] duty_in=0;reg [1:0] raw=0;reg signed [15:0] origin=0;
    wire hi,lo,boundary,config_error,step,invalid,wrapped;wire [31:0] phase,active_duty,shadow_duty,invalid_count;wire signed [15:0] position;
    safe_pwm #(.PERIOD(PERIOD),.DEAD(DEAD),.MUTATION(MUTATION==1 || MUTATION==3 || MUTATION==5 ? MUTATION:0)) pwm(.*);
    quadrature_decoder #(.FILTER(FILTER),.MUTATION(MUTATION==2 || MUTATION==4 ? MUTATION:0)) encoder(.clk(clk),.rst_n(rst_n),.a(raw[1]),.b(raw[0]),.origin_en(origin_en),.origin(origin),.position(position),.step(step),.invalid(invalid),.wrapped(wrapped),.invalid_count(invalid_count));
    always #5 clk=~clk;
    reg [31:0] v[0:7],e[0:21],obs[0:21];reg old_rst=0;reg signed [15:0] old_pos;integer fd,ef,rc,checks,rows=0,resets=0,steps=0,invalids=0,wraps=0,rejected=0,boundaries=0;
    integer last_on=0,off_cycles=999;
    string vectors,expected,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d phase=%0d pos=%0d",rows,phase,position);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("CHECKS=%d",checks))$fatal(1,"arguments required");
        fd=$fopen(vectors,"r");ef=$fopen(expected,"r");if(!fd||!ef)$fatal(1,"inputs missing");$dumpfile(wave);$dumpvars(2,motion_io_tb);@(negedge clk);
        while(!$feof(fd))begin
            for(integer j=0;j<8;j=j+1)begin rc=$fscanf(fd,"%h\n",v[j]);if(rc!=1)$fatal(1,"bad input");end
            for(integer j=0;j<22;j=j+1)begin rc=$fscanf(ef,"%h\n",e[j]);if(rc!=1)$fatal(1,"bad oracle");end
            for(integer j=0;j<8;j=j+1)if((j==0||j==1||j==2||j==3||j==6) && v[j]>1)fail("IO_INPUT_RANGE");
            if(v[5]>3 || v[7]!==32'($signed(v[7][15:0])))fail("IO_INPUT_RANGE");
            rst_n=v[0][0];enable=v[1][0];stop=v[2][0];load=v[3][0];duty_in=v[4];raw=v[5][1:0];origin_en=v[6][0];origin=v[7][15:0];#1;
            if(old_rst&&!rst_n)begin resets=resets+1;$display("COVER reset/active");end old_rst=rst_n;old_pos=position;
            if(rst_n)begin
                if(enable&&load&&duty_in<=PERIOD&&pwm.running&&phase!=PERIOD-1)$display("COVER pwm/update-deferred");
                if(enable&&load&&duty_in<=PERIOD&&pwm.running&&phase==PERIOD-1)$display("COVER pwm/update-boundary");
                if(origin_en)$display("COVER encoder/origin");
                if(origin_en&&encoder.previous!=encoder.next_filtered)$display("COVER encoder/origin-priority");
                if(encoder.candidate!=encoder.sync2 && encoder.stable<FILTER && encoder.filtered==encoder.previous)$display("COVER encoder/filter-delay");
            end
            @(posedge clk);#1;rows=rows+1;
            if(hi&&lo)fail("IO_OVERLAP");
            if(hi||lo)begin
                if(last_on!=0 && last_on!=(hi ? 1:2) && off_cycles<DEAD)fail("IO_DEADTIME");last_on=hi ? 1:2;off_cycles=0;
            end else off_cycles=off_cycles+1;
            obs[0]=32'(hi);obs[1]=32'(lo);obs[2]=32'(boundary);obs[3]=32'(config_error);obs[4]=phase;obs[5]=active_duty;obs[6]=shadow_duty;
            obs[7]=32'(pwm.drive);obs[8]=pwm.gap;obs[9]=32'(pwm.target);obs[10]=32'(pwm.running);obs[11]=32'(position);obs[12]=32'(step);obs[13]=32'(invalid);obs[14]=32'(wrapped);obs[15]=invalid_count;
            obs[16]=32'(encoder.sync1);obs[17]=32'(encoder.sync2);obs[18]=32'(encoder.candidate);obs[19]=32'(encoder.filtered);obs[20]=32'(encoder.previous);obs[21]=encoder.stable;
            for(integer j=0;j<22;j=j+1)if(obs[j]!==e[j])begin $display("FIELD %0d actual=%h expected=%h",j,obs[j],e[j]);if(j<11)fail("IO_PWM");else fail("IO_ENCODER");end
            if(rst_n)begin
                steps=steps+int'(step);invalids=invalids+int'(invalid);wraps=wraps+int'(wrapped);rejected=rejected+int'(config_error);boundaries=boundaries+int'(boundary);
                if(enable&&!stop&&pwm.drive==0)$display("COVER pwm/deadtime");
                if(enable&&active_duty==0)$display("COVER pwm/zero");if(enable&&active_duty==PERIOD)$display("COVER pwm/full");
                if(enable&&active_duty==PERIOD/2)$display("COVER pwm/half");if(stop&&!hi&&!lo)$display("COVER pwm/stop");if(config_error)$display("COVER pwm/reject");
                if(step)begin if(position==16'(old_pos+16'sd1))$display("COVER encoder/forward");else $display("COVER encoder/reverse");end
                if(invalid)$display("COVER encoder/invalid");if(wrapped)$display("COVER encoder/wrap");
            end
            @(negedge clk);
        end
        if(!$feof(ef) || pwm.running || encoder.sync1!=encoder.sync2 || encoder.sync2!=encoder.filtered || encoder.filtered!=encoder.previous)fail("IO_COMPLETION");
        $display("COUNT rows=%0d",rows);$display("COUNT resets=%0d",resets);$display("COUNT steps=%0d",steps);$display("COUNT invalid=%0d",invalids);$display("COUNT wraps=%0d",wraps);$display("COUNT rejected=%0d",rejected);$display("COUNT boundaries=%0d",boundaries);
        if(rows!=checks)fail("IO_COMPLETION");$display("RESULT PASS checks=%0d",rows);$fclose(fd);$fclose(ef);$finish;
    end
endmodule
