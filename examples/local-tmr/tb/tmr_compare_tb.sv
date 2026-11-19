`timescale 1ns/1ps
// Three DUTs share functional inputs; the golden state never sees DUT state or faults.
module tmr_compare_tb;
    parameter WIDTH=32, MUTATION=0;
    reg clk=0, rst_n=0, write_en=0;
    reg [WIDTH-1:0] write_data=0, plain_fault=0, fault0=0, fault1=0, fault2=0;
    reg [WIDTH-1:0] golden=0;
    wire [WIDTH-1:0] plain_q, vote_q, repair_q;
    wire vote_bad, repair_bad, vote_attempt, repair_attempt;
    plain_register #(.WIDTH(WIDTH)) plain (
        .clk(clk), .rst_n(rst_n), .write_en(write_en), .write_data(write_data),
        .fault_xor(plain_fault), .q(plain_q)
    );
    tmr_register #(.WIDTH(WIDTH), .MUTATION(MUTATION)) vote_only (
        .clk(clk), .rst_n(rst_n), .write_en(write_en), .repair_en(1'b0),
        .write_data(write_data), .fault0(fault0), .fault1(fault1), .fault2(fault2),
        .voted(vote_q), .disagreement(vote_bad), .repair_attempt(vote_attempt)
    );
    tmr_register #(.WIDTH(WIDTH), .MUTATION(MUTATION)) auto_repair (
        .clk(clk), .rst_n(rst_n), .write_en(write_en), .repair_en(1'b1),
        .write_data(write_data), .fault0(fault0), .fault1(fault1), .fault2(fault2),
        .voted(repair_q), .disagreement(repair_bad), .repair_attempt(repair_attempt)
    );
    always #5 clk=~clk;
    integer cycle=0;
    always @(posedge clk) begin
        cycle <= cycle+1;
        if (!rst_n) golden <= {WIDTH{1'b0}};
        else if (write_en) golden <= write_data;
    end

    integer checks=0, single_trials=0, stuck_trials=0, limit_trials=0;
    integer multi_trials=0, random_steps=64, random_trials=0, normal_patterns=0;
    reg [31:0] seed=17, rng_state, random_word;
    reg [WIDTH-1:0] alternating, mask, m0, m1, m2, data_word;
    reg [WIDTH-1:0] last_plain=0, last0=0, last1=0, last2=0;
    integer lane, bit_index, action;
    integer phase_id=0;
    reg stuck_active=0, stuck_fixed=0;
    // What lane 0 holds while its bit 0 is stuck: the fixed bit, and above it what the fault-free
    // lane 1 holds, since both lanes take the same writes and repairs.
    wire [WIDTH-1:0] stuck_vote=(vote_only.q1 & ~WIDTH'(1)) | WIDTH'(stuck_fixed);
    wire [WIDTH-1:0] stuck_repair=(auto_repair.q1 & ~WIDTH'(1)) | WIDTH'(stuck_fixed);
    string wave, phase="startup", target="none", fault_kind="none";

    task check(input logic ok, input string configuration, input string label);
        begin
            checks=checks+1;
            if (ok !== 1'b1) begin
                $display("CHECK_FAIL TMR_COMPARE %s",label);
                $display("seed=%0d cycle=%0d width=%0d configuration=%s phase=%s fault=%s target=%s",
                         seed,cycle,WIDTH,configuration,phase,fault_kind,target);
                $display("last_masks plain=%h lane0=%h lane1=%h lane2=%h expected=%h plain=%h write_en=%b",
                         last_plain,last0,last1,last2,golden,plain_q,write_en);
                $display("vote_only q0=%h q1=%h q2=%h voted=%h mismatch=%b attempt=%b",
                         vote_only.q0,vote_only.q1,vote_only.q2,vote_q,vote_bad,vote_attempt);
                $display("auto_repair q0=%h q1=%h q2=%h voted=%h mismatch=%b attempt=%b",
                         auto_repair.q0,auto_repair.q1,auto_repair.q2,repair_q,repair_bad,repair_attempt);
                $fatal(1,"unexpected register behavior");
            end
        end
    endtask

    task check_plain(input reg [WIDTH-1:0] expected);
        check(plain_q === expected && (^plain_q !== 1'bx),"plain","stored value");
    endtask

    task check_tmr(input logic repairing, input reg [WIDTH-1:0] e0,e1,e2,output_value,
                   input logic mismatch,attempt);
        begin
            if (repairing) begin
                check(auto_repair.q0 === e0 && auto_repair.q1 === e1 && auto_repair.q2 === e2 &&
                      (^{auto_repair.q0,auto_repair.q1,auto_repair.q2} !== 1'bx),
                      "auto_repair","internal state");
                check(repair_q === output_value && (^repair_q !== 1'bx) &&
                      repair_bad === mismatch && repair_attempt === attempt,
                      "auto_repair","vote and status");
            end else begin
                check(vote_only.q0 === e0 && vote_only.q1 === e1 && vote_only.q2 === e2 &&
                      (^{vote_only.q0,vote_only.q1,vote_only.q2} !== 1'bx),
                      "vote_only","internal state");
                check(vote_q === output_value && (^vote_q !== 1'bx) &&
                      vote_bad === mismatch && vote_attempt === attempt,
                      "vote_only","vote and status");
            end
        end
    endtask

    task check_clean;
        begin
            check_plain(golden);
            check_tmr(0,golden,golden,golden,golden,0,0);
            check_tmr(1,golden,golden,golden,golden,0,0);
        end
    endtask

    // Functional inputs and fault controls change only on falling edges.
    // Every observation is 1 ns after a rising edge (after NBA and combinational settling).
    task drive(input logic reset_value,enable, input reg [WIDTH-1:0] data,pf,f0,f1,f2);
        begin
            @(negedge clk);
            rst_n=reset_value; write_en=enable; write_data=data;
            plain_fault=pf; fault0=f0; fault1=f1; fault2=f2;
            @(posedge clk); #1;
        end
    endtask

    task write_clean(input reg [WIDTH-1:0] data);
        begin
            drive(1,1,data,0,0,0,0);
            check_clean();
        end
    endtask

    task hold_clean;
        begin
            drive(1,0,0,0,0,0,0);
            check_clean();
        end
    endtask

    task inject_tmr(input reg [WIDTH-1:0] f0,f1,f2);
        begin
            fault_kind="SEU"; target="TMR lanes 0/1/2";
            last_plain=0; last0=f0; last1=f1; last2=f2;
            drive(1,0,0,0,f0,f1,f2);
        end
    endtask

    // Expected states are derived from the fault-free write history and stimulus masks.
    // This task is only used when every bit has at most one faulty replica.
    task protected_fault(input reg [WIDTH-1:0] f0,f1,f2);
        begin
            inject_tmr(f0,f1,f2);
            check_plain(golden);
            check_tmr(0,golden^f0,golden^f1,golden^f2,golden,1,0);
            check_tmr(1,golden^f0,golden^f1,golden^f2,golden,1,0);
            // The upset above must be observed before the first repair-eligible edge.
            drive(1,0,0,0,0,0,0);
            check(write_en === 1'b0,"auto_repair","repair without software write");
            check_tmr(1,golden,golden,golden,golden,0,1);
            check_tmr(0,golden^f0,golden^f1,golden^f2,golden,1,0);
            drive(1,0,0,0,0,0,0);
            check_tmr(1,golden,golden,golden,golden,0,0);
            check_tmr(0,golden^f0,golden^f1,golden^f2,golden,1,0);
            write_clean(golden);
        end
    endtask

    function automatic [31:0] random_next(input reg [31:0] state);
        reg [31:0] value;
        begin
            value=state ^ (state << 13);
            value=value ^ (value >> 17);
            random_next=value ^ (value << 5);
        end
    endfunction

    initial begin
        if (WIDTH < 1 || WIDTH > 32) $fatal(1,"comparison supports WIDTH 1 through 32");
        if ($value$plusargs("SEED=%d",seed)) begin end
        if ($value$plusargs("STEPS=%d",random_steps)) begin end
        if (random_steps < 1) $fatal(1,"STEPS must be positive");
        rng_state=seed == 0 ? 32'h6d2b79f5 : seed;
        if ($value$plusargs("WAVE=%s",wave)) begin
            $dumpfile(wave); $dumpvars(0,tmr_compare_tb);
        end
        alternating=0;
        for (integer b=0; b<WIDTH; b=b+1) alternating[b]=(b%2)==1;
        $display("CONFIG width=%0d seed=%0d random_steps=%0d",WIDTH,seed,random_steps);

        phase_id=1; phase="reset and functional patterns";
        drive(0,1,{WIDTH{1'b1}},{WIDTH{1'b1}},{WIDTH{1'b1}},{WIDTH{1'b1}},{WIDTH{1'b1}});
        check_clean();
        for (integer pattern=0; pattern<4; pattern=pattern+1) begin
            case (pattern)
                0: data_word=0;
                1: data_word={WIDTH{1'b1}};
                2: data_word=alternating;
                3: data_word=~alternating;
            endcase
            write_clean(data_word); repeat (2) hold_clean(); normal_patterns=normal_patterns+1;
        end
        $display("PASS fault_free reset write hold");

        phase_id=2; phase="plain register persistent SEU"; fault_kind="SEU"; target="plain bit 0";
        write_clean(alternating); last_plain=WIDTH'(1);
        drive(1,0,0,WIDTH'(1),0,0,0);
        check_plain(golden ^ WIDTH'(1));
        check(plain_q !== golden,"plain","SEU changes output");
        repeat (3) begin drive(1,0,0,0,0,0,0); check_plain(golden ^ WIDTH'(1)); end
        write_clean(~alternating);
        $display("PASS plain_seu persists until normal write");

        phase_id=3; phase="all lanes and all bit positions";
        for (lane=0; lane<3; lane=lane+1) begin
            for (bit_index=0; bit_index<WIDTH; bit_index=bit_index+1) begin
                write_clean((bit_index%2)==0 ? alternating : ~alternating);
                mask=WIDTH'(1) << bit_index;
                protected_fault(lane==0 ? mask : 0,lane==1 ? mask : 0,lane==2 ? mask : 0);
                single_trials=single_trials+1;
            end
        end
        $display("PASS single_seu trials=%0d vote_only_retains auto_repair_restores",single_trials);

        phase_id=4; phase="one lane multiple bits";
        write_clean(alternating); protected_fault({WIDTH{1'b1}},0,0); multi_trials=multi_trials+1;
        if (WIDTH > 1) begin
            phase_id=5; phase="different lanes different bit positions";
            write_clean(alternating); protected_fault(WIDTH'(1),WIDTH'(2),0); multi_trials=multi_trials+1;
            $display("PASS disjoint_lane_faults correct bitwise majority");
        end else $display("NOT_APPLICABLE disjoint_lane_faults WIDTH=1");

        phase_id=6; phase="two lanes same bit";
        write_clean(0); inject_tmr(WIDTH'(1),WIDTH'(1),0);
        check_tmr(0,WIDTH'(1),WIDTH'(1),0,WIDTH'(1),1,0);
        check_tmr(1,WIDTH'(1),WIDTH'(1),0,WIDTH'(1),1,0);
        check(vote_q !== golden && repair_q !== golden,"both_TMR","wrong majority detected");
        limit_trials=limit_trials+1;
        $display("EXPECTED_LIMITATION same_bit_two_lanes wrong vote with mismatch=1");
        phase_id=7; phase="wrong majority repair";
        drive(1,0,0,0,0,0,0);
        check_tmr(1,WIDTH'(1),WIDTH'(1),WIDTH'(1),WIDTH'(1),0,1);
        check(repair_q !== golden && write_en === 1'b0,"auto_repair","wrong majority propagated");
        limit_trials=limit_trials+1;
        $display("EXPECTED_LIMITATION wrong_repair wrong data with mismatch=0");
        phase_id=8; phase="three lanes same error";
        write_clean(0); inject_tmr(WIDTH'(1),WIDTH'(1),WIDTH'(1));
        check_tmr(0,WIDTH'(1),WIDTH'(1),WIDTH'(1),WIDTH'(1),0,0);
        check_tmr(1,WIDTH'(1),WIDTH'(1),WIDTH'(1),WIDTH'(1),0,0);
        check(vote_q !== golden && repair_q !== golden,"both_TMR","common error invisible");
        limit_trials=limit_trials+1;
        $display("EXPECTED_LIMITATION three_lanes_same_error wrong data with mismatch=0");

        // A force models stuck-at, not a repeated XOR pulse. IEEE 1800-2023 10.6.2 does not allow a
        // force on a bit-select of a variable, so the whole lane is forced to stuck_vote/stuck_repair.
        // It overrides procedural updates while active. Release leaves a variable's
        // forced value in storage until the next procedural assignment updates it.
        for (integer stuck_value=0; stuck_value<2; stuck_value=stuck_value+1) begin
            phase_id=9+stuck_value;
            phase="persistent stuck-at lane 0 bit 0"; fault_kind="stuck-at";
            target=$sformatf("lane 0 bit 0 fixed=%0d",stuck_value);
            last_plain=0; last0=WIDTH'(1); last1=0; last2=0;
            data_word={WIDTH{1'b1}}; data_word[0]=!stuck_value;
            write_clean(data_word);
            @(negedge clk); write_en=0; stuck_active=1; stuck_fixed=1'(stuck_value);
            force vote_only.q0=stuck_vote; force auto_repair.q0=stuck_repair;
            #1;
            check_tmr(0,golden^WIDTH'(1),golden,golden,golden,1,0);
            check_tmr(1,golden^WIDTH'(1),golden,golden,golden,1,0);
            repeat (3) begin
                drive(1,0,0,0,0,0,0);
                check_tmr(0,golden^WIDTH'(1),golden,golden,golden,1,0);
                check_tmr(1,golden^WIDTH'(1),golden,golden,golden,1,1);
            end
            data_word=~data_word; data_word[0]=!stuck_value;
            drive(1,1,data_word,0,0,0,0);
            check_plain(golden);
            check_tmr(0,golden^WIDTH'(1),golden,golden,golden,1,0);
            check_tmr(1,golden^WIDTH'(1),golden,golden,golden,1,0);
            @(negedge clk); write_en=0;
            release vote_only.q0; release auto_repair.q0;
            stuck_active=0;
            #1;
            check_tmr(0,golden^WIDTH'(1),golden,golden,golden,1,0);
            check_tmr(1,golden^WIDTH'(1),golden,golden,golden,1,0);
            // Observe the very next edge: drive() would wait for another falling edge.
            @(posedge clk); #1;
            check_tmr(1,golden,golden,golden,golden,0,1);
            check_tmr(0,golden^WIDTH'(1),golden,golden,golden,1,0);
            write_clean(golden); stuck_trials=stuck_trials+1;
            $display("PASS stuck_at value=%0d write_and_repair_blocked release_then_recover",stuck_value);
        end

        phase_id=11; phase="seeded random single-fault trials"; fault_kind="none"; target="none";
        write_clean(alternating);
        for (integer step=0; step<random_steps; step=step+1) begin
            rng_state=random_next(rng_state); action=int'(rng_state%3);
            rng_state=random_next(rng_state); random_word=rng_state;
            $display("RANDOM step=%0d action=%0d word=%08h",step,action,random_word);
            case (action)
                0: write_clean(WIDTH'(random_word));
                1: hold_clean();
                2: begin
                    // Reinitialize vote-only storage before each independent fault.
                    write_clean(WIDTH'(random_word));
                    lane=int'(random_word%3); bit_index=int'((random_word>>2)%WIDTH);
                    mask=WIDTH'(1) << bit_index;
                    protected_fault(lane==0 ? mask : 0,lane==1 ? mask : 0,lane==2 ? mask : 0);
                end
            endcase
            random_trials=random_trials+1;
        end
        phase_id=12; phase="final reset";
        drive(0,1,{WIDTH{1'b1}},0,WIDTH'(1),WIDTH'(1),WIDTH'(1)); check_clean();
        $display("COUNT normal_patterns=%0d",normal_patterns);
        $display("COUNT single_trials=%0d",single_trials);
        $display("COUNT multi_trials=%0d",multi_trials);
        $display("COUNT limit_trials=%0d",limit_trials);
        $display("COUNT stuck_trials=%0d",stuck_trials);
        $display("COUNT random_steps=%0d",random_trials);
        $display("RESULT PASS checks=%0d",checks);
        $finish;
    end
    initial begin #1000000; $fatal(1,"comparison watchdog expired"); end
endmodule
