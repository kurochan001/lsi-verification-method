`timescale 1ns/1ps
module motion_axis_tb;
    parameter PERIOD=16,DEAD=2,FILTER=2,SAMPLE=64,LATENCY=3,SPEED_LIMIT=6,MUTATION=0;
    reg clk=0,rst_n=0,arm=0,disarm=0,ack=0,estop=0,compute_hold=0,origin_en=0,encoder_a=0,encoder_b=0;
    reg signed [15:0] target=0,origin=0;
    wire pwm_hi,pwm_lo,armed,irq,updated,cancelled,sampled;wire [5:0] cause;wire signed [15:0] position;wire signed [7:0] effort;
    motion_axis #(.PERIOD(PERIOD),.DEAD(DEAD),.FILTER(FILTER),.SAMPLE(SAMPLE),.LATENCY(LATENCY),.SPEED_LIMIT(SPEED_LIMIT),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [31:0] v[0:13],e[0:44],obs[0:44];integer fd,ef,rc,checks,rows=0,resets=0,samples=0,updates=0,cancels=0,reset_cancels=0;
    integer plant_position=0,plant_velocity=0,load_torque=0,raw_phase=0,frozen_phase=0,old_mode=0,mode=0;
    reg freeze=0,pre_hi,pre_lo,old_rst=0,old_armed,neutral_needed=0;reg [5:0] old_cause;reg signed [15:0] velocity_before;integer last_on=0,off_cycles=999;
    string vectors,expected,wave;
    function automatic integer gray(input integer n);case(n&3)0:gray=0;1:gray=1;2:gray=3;default:gray=2;endcase endfunction
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d pos=%0d velocity=%0d cause=%h",rows,position,plant_velocity,cause);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("CHECKS=%d",checks))$fatal(1,"arguments required");
        fd=$fopen(vectors,"r");ef=$fopen(expected,"r");if(!fd||!ef)$fatal(1,"inputs missing");$dumpfile(wave);$dumpvars(2,motion_axis_tb);@(negedge clk);
        while(!$feof(fd))begin
            for(integer j=0;j<14;j=j+1)begin rc=$fscanf(fd,"%h\n",v[j]);if(rc!=1)$fatal(1,"bad input");end
            for(integer j=0;j<45;j=j+1)begin rc=$fscanf(ef,"%h\n",e[j]);if(rc!=1)$fatal(1,"bad oracle");end
            for(integer j=0;j<14;j=j+1)if((j<=4||j==6||j==8||j==10||j==13)&&v[j]>1)fail("AXIS_INPUT_RANGE");
            if(v[5]!==32'($signed(v[5][15:0])) || v[7]!==32'($signed(v[7][15:0])) || $signed(v[9])< -1024 || $signed(v[9])>1024 || v[11]>2 || v[12]>3)fail("AXIS_INPUT_RANGE");
            rst_n=v[0][0];arm=v[1][0];disarm=v[2][0];ack=v[3][0];estop=v[4][0];target=v[5][15:0];origin_en=v[6][0];origin=v[7][15:0];compute_hold=v[8][0];load_torque=$signed(v[9]);freeze=v[10][0];mode=int'(v[11]);
            if(!rst_n)raw_phase=0;
            else if(mode==1)begin if(old_mode!=1)frozen_phase=gray(plant_position>>>12);raw_phase=frozen_phase;end
            else raw_phase=mode==2 ? int'(v[12]):gray(plant_position>>>12);
            encoder_a=raw_phase[1];encoder_b=raw_phase[0];#1;
            old_armed=armed;old_cause=cause;pre_hi=pwm_hi;pre_lo=pwm_lo;velocity_before=dut.velocity;
            if(old_rst&&!rst_n)begin resets=resets+1;reset_cancels=reset_cancels+int'(dut.busy||dut.done);if(dut.busy||dut.done)$display("COVER reset/pending");end old_rst=rst_n;
            if(rst_n&&origin_en&&old_armed)$display("COVER origin/ignored-running");
            if(rst_n&&origin_en&&arm&&!old_armed)$display("COVER origin/atomic-arm");
            if(rst_n&&dut.tick&&dut.done&&dut.event_cause==0)$display("COVER deadline/boundary-on-time");
            if(rst_n&&arm&&!old_armed&&!estop&&dut.enc_invalid)$display("COVER recovery/arm-refused-encoder");
            if(rst_n&&arm&&!old_armed&&!estop&&dut.enc_wrapped)$display("COVER recovery/arm-refused-wrap");
            if(rst_n&&dut.enabled&&dut.busy&&!compute_hold&&dut.controller.remaining==0)begin
                if(dut.controller.rounded==PERIOD/2+1)$display("COVER control/limit-plus-one");
                if(dut.controller.rounded==-(PERIOD/2)-1)$display("COVER control/limit-minus-one");
            end
            @(posedge clk);#1;rows=rows+1;
            if(!rst_n)begin plant_position=0;plant_velocity=0;raw_phase=0;frozen_phase=0;old_mode=0;neutral_needed=0;end
            else begin
                if(freeze)plant_velocity=0;
                else begin plant_velocity=(15*plant_velocity+256*(int'(pre_hi)-int'(pre_lo))-load_torque)/16;plant_position=plant_position+plant_velocity;end
                old_mode=mode;
            end
            if(pwm_hi&&pwm_lo)fail("AXIS_PWM");
            if(pwm_hi||pwm_lo)begin if(last_on!=0 && last_on!=(pwm_hi ? 1:2) && off_cycles<DEAD)fail("AXIS_DEADTIME");last_on=pwm_hi ? 1:2;off_cycles=0;end else off_cycles=off_cycles+1;
            if(rst_n&&!old_armed&&armed)begin neutral_needed=1;if(old_cause!=0)$display("COVER recovery/explicit-arm");end
            if(updated)neutral_needed=0;
            if(armed&&neutral_needed&&dut.pwm.running&&dut.active_duty!=PERIOD/2)fail("AXIS_STALE_COMMAND");
            obs[0]=32'(armed);obs[1]=32'(cause);obs[2]=32'(irq);obs[3]=32'(updated);obs[4]=32'(cancelled);obs[5]=32'(sampled);obs[6]=32'(position);
            obs[7]=32'(effort);obs[8]=dut.integral;obs[9]=32'(dut.busy);obs[10]=32'(dut.done);obs[11]=32'(dut.clipped);obs[12]=32'(dut.antiwindup);obs[13]=dut.controller.remaining;obs[14]=32'(dut.controller.saved_error);
            obs[15]=dut.sample_phase;obs[16]=dut.stalled;obs[17]=32'(dut.last_position);obs[18]=32'(pwm_hi);obs[19]=32'(pwm_lo);obs[20]=32'(dut.boundary);obs[21]=32'(dut.config_error);obs[22]=dut.phase;obs[23]=dut.active_duty;obs[24]=dut.shadow_duty;obs[25]=32'(dut.pwm.drive);obs[26]=dut.pwm.gap;obs[27]=32'(dut.pwm.target);obs[28]=32'(dut.pwm.running);
            obs[29]=32'(dut.enc_step);obs[30]=32'(dut.enc_invalid);obs[31]=32'(dut.enc_wrapped);obs[32]=dut.enc_errors;obs[33]=32'(dut.encoder.sync1);obs[34]=32'(dut.encoder.sync2);obs[35]=32'(dut.encoder.candidate);obs[36]=32'(dut.encoder.filtered);obs[37]=32'(dut.encoder.previous);obs[38]=dut.encoder.stable;
            obs[39]=32'(plant_position);obs[40]=32'(plant_velocity);obs[41]=32'(raw_phase);obs[42]=32'(frozen_phase);obs[43]=32'(old_mode);obs[44]=32'(dut.event_cause);
            if(obs[44]!==e[44])fail("AXIS_STATE");
            for(integer j=0;j<45;j=j+1)if(obs[j]!==e[j])begin
                $display("FIELD %0d actual=%h expected=%h",j,obs[j],e[j]);
                if(j<6 || j==44)fail("AXIS_STATE");else if(j>=7&&j<=14)fail("AXIS_PI");else if(j>=18&&j<=28)fail("AXIS_PWM");else fail("AXIS_MODEL");
            end
            if(rst_n)begin
                samples=samples+int'(sampled);updates=updates+int'(updated);cancels=cancels+int'(cancelled);
                if(ack&&estop&&irq&&!armed)$display("COVER fault/ack-priority");
                if(updated)$display("COVER control/update");if(dut.clipped)$display("COVER control/saturation");if(dut.antiwindup)$display("COVER control/antiwindup");
                if(effort>0)$display("COVER control/positive");if(effort<0)$display("COVER control/negative");
                if(cancelled&&cause!=0)$display("COVER fault/cancel");if(ack&&!armed&&old_cause!=0)$display("COVER recovery/ack-keeps-off");
                if(!old_armed&&armed&&old_cause!=0)$display("COVER recovery/neutral");
                if(old_armed&&!armed&&cause!=0)begin
                    if(cause[0])$display("COVER fault/estop");if(cause[1])$display("COVER fault/encoder");if(cause[2])$display("COVER fault/deadline");if(cause[3])$display("COVER fault/progress");if(cause[4])$display("COVER fault/overspeed");if(cause[4]&&velocity_before<0)$display("COVER fault/overspeed-negative");if(cause[5])$display("COVER fault/wrap");
                end
                if(v[13]!=0)begin
                    if(!armed || cause!=0 || int'(position)-int'(target)>2 || int'(target)-int'(position)>2 || (plant_position>>>12)-int'(target)>3 || int'(target)-(plant_position>>>12)>3)fail("AXIS_TRACKING");
                    $display("COVER control/settled");if(load_torque!=0)$display("COVER control/load-rejection");
                end
            end
            @(negedge clk);
        end
        if(!$feof(ef)||armed||dut.busy||dut.done||pwm_hi||pwm_lo||samples!=updates+cancels+reset_cancels)fail("AXIS_COMPLETION");
        $display("COUNT rows=%0d",rows);$display("COUNT resets=%0d",resets);$display("COUNT samples=%0d",samples);$display("COUNT updates=%0d",updates);$display("COUNT cancels=%0d",cancels);$display("COUNT reset_cancels=%0d",reset_cancels);
        if(rows!=checks)fail("AXIS_COMPLETION");$display("RESULT PASS checks=%0d",rows);$fclose(fd);$fclose(ef);$finish;
    end
endmodule
