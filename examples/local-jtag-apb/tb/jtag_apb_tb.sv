`timescale 1ns/1ps
module jtag_apb_tb;
    parameter WAIT=0, MUTATION=0;
    reg tck=0, trst_n=1, tms=1, tdi=0, extra_wait=0;
    wire tdo, psel, penable, pwrite, err;
    wire [7:0] paddr, pwdata;
    wire [3:0] state;
    wire [1:0] ir;
    integer waited, idx;
    reg [7:0] ram[0:7];
    wire [7:0] prdata = ram[paddr[2:0]];
    wire pready = waited == WAIT && !extra_wait;
    wire pslverr = paddr[7];
    jtag_apb #(.MUTATION(MUTATION)) dut(.*);
    always #5 tck = ~tck;
    always @(posedge tck or negedge trst_n) begin
        if (!trst_n) begin
            waited <= 0;
            for (idx=0; idx<8; idx=idx+1) ram[idx] <= 0;
        end else if (psel && penable) begin
            if (pready) begin
                if (pwrite && !pslverr) ram[paddr[2:0]] <= pwdata;
                waited <= 0;
            end else if (waited < WAIT) waited <= waited + 1;
        end else waited <= 0;
    end
    reg [31:0] v[0:11];
    reg [3:0] old_state;
    reg [1:0] old_ir;
    reg old_err, old_ready, old_sel, old_enable, old_write, old_slave_error;
    integer n, fd, checks=0, shifts=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label); $fatal(1,"row=%0d state=%d ir=%h phase=%b%b tdo=%b expected=%b",
              checks,state,ir,psel,penable,tdo,v[4][0]); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave)) $fatal(1);
        fd=$fopen(vectors,"r"); if (!fd) $fatal(1);
        $dumpfile(wave); $dumpvars(0,jtag_apb_tb);
        while (!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",
                      v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);
            if (n!=12) $fatal(1,"bad row");
            @(negedge tck);
            trst_n=v[0]; tms=v[1]; tdi=v[2]; extra_wait=v[3]; #1;
            old_state=state; old_ir=ir; old_err=err; old_ready=pready; old_sel=psel;
            old_enable=penable; old_write=pwrite; old_slave_error=pslverr;
            @(posedge tck); #1;
            if (state!==v[5][3:0] || ir!==v[6][1:0] || tdo!==v[4][0]) fail("JAPB_TAP");
            if (psel!==(v[7]!=0) || penable!==(v[7]==2) || err!==v[11][0]) fail("JAPB_ERR");
            if (pwrite!==v[8][0] || paddr!==v[9][7:0] || pwdata!==v[10][7:0]) fail("JAPB_DATA");
            if (!trst_n && state==0 && ir==1) $display("COVER tap/reset");
            if (trst_n && tms && state==0) $display("COVER tap/tlr");
            if (old_state==11 && state==12) $display("COVER ir/shift");
            if (old_state==3) shifts=0;
            if (old_state==4) begin
                shifts=shifts+1;
                if (old_ir==1 && shifts==32 && tms) $display("COVER idcode/scan");
                if (old_ir==2 && shifts>1 && tdo) $display("COVER bypass/drift");
                if (old_ir==3 && shifts==1 && tdo && err) $display("COVER err/scan-observe");
            end
            if (old_sel && old_enable) begin
                if (!old_ready) $display("COVER apb/wait-observed");
                else begin
                    if (old_write && !old_slave_error) $display("COVER apb/write");
                    if (!old_write && !old_slave_error) $display("COVER apb/read");
                    if (old_slave_error && err) $display("COVER apb/pslverr");
                    if (!psel && !penable) $display("COVER apb/idle");
                end
            end
            if (old_err && err && !old_sel) $display("COVER err/sticky");
            if (old_err && !err && old_enable && old_ready && !old_write) $display("COVER err/clear");
            checks=checks+1;
        end
        $fclose(fd); $display("COUNT steps=%0d",checks); $display("RESULT PASS checks=%0d",checks); $finish;
    end
endmodule
