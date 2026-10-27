`timescale 1ns/1ps
module ahb_tb;
    parameter WAIT_CYCLES=0,MUTATION=0;
    reg hclk=0;always #5 hclk=!hclk;
    reg hresetn=0,hsel=0,hwrite=0;
    reg [1:0] htrans=0;reg [2:0] hsize=2,hburst=0;
    reg [9:0] haddr=0;reg [31:0] hwdata=0;
    wire hreadyout,hresp;wire [31:0] hrdata;
    wire hready=hreadyout; // Single slave bus, no response multiplexor.
    ahb_regs #(.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(.*);
`ifdef BUS_VALIDATION
    ahb_protocol_checker protocol_checker(hclk,hresetn,hsel,hready,hresp,hwrite,htrans,hsize,hburst,haddr,hwdata,hrdata);
    integer perf_start=-1,perf_last=-1,perf_done=0;
`endif
    integer fd,fields,rst,sel,trans,address,write,size,burst,data,ready,response,read_value,active,dw,da,ds;
    integer expected_regs[0:3];
    integer checks=0,accepted=0,reads=0,writes=0,errors=0,waits=0,age=0;
    bit first_error=0,recovering=0;
    string vectors,wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d addr=%h trans=%b ready=%b resp=%b",checks,haddr,htrans,hreadyout,hresp);end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,ahb_tb);end
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot open vectors");
        repeat(2) @(negedge hclk);
        while(!$feof(fd)) begin
            fields=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                rst,sel,trans,address,write,size,burst,data,ready,response,read_value,active,dw,da,ds,
                expected_regs[0],expected_regs[1],expected_regs[2],expected_regs[3]);
            if(fields!=19) $fatal(1,"malformed vector");
            if(!rst && dut.active) begin $display("COVER reset/active");recovering=1;end
            hresetn=rst;hsel=sel;htrans=trans;haddr=address;hwrite=write;hsize=size;hburst=burst;hwdata=data;
            #1;
            if(hreadyout!==ready[0] || hresp!==response[0]) fail("AHB_RESPONSE");
            if(active && hreadyout && !hresp && !dw && hrdata!==read_value[31:0]) fail("AHB_DATA");
            if(!rst) begin age=0;first_error=0;end
            else begin
                if(active) begin
                    age=age+1;
                    if(!hreadyout) waits=waits+1;
                    if(hresp && !hreadyout) first_error=1;
                    if(hreadyout) begin
                        if(age!=WAIT_CYCLES+1+(hresp ? 1 : 0)) fail("AHB_LATENCY");
                        $display("COVER bus/wait-policy");
`ifdef BUS_VALIDATION
                        perf_done=perf_done+1;perf_last=checks;
                        $display("PERF ahb latency=%0d cycle=%0d",age,checks);
                        if(ds<=2) $display("CROSS ahb/op%0d/size%0d/resp%0d",dw,ds,hresp);
`endif
                        if(hresp) begin
                            errors=errors+1;
                            if(!first_error) fail("AHB_ERROR_PHASE");
                            $display("COVER error/two-cycle");
                            if(htrans==0) $display("COVER error/cancel");
                            if(ds>2) $display("COVER error/size");
                            else if((da & ((1<<ds)-1))!=0) $display("COVER error/alignment");
                            else if(da>=20) $display("COVER error/address");
                            else if(dw && da>=16) $display("COVER error/readonly");
                        end else begin
                            if(dw) begin
                                writes=writes+1;
                                if(ds==2 && hwdata==0) $display("COVER data/zero");
                                if(ds==2 && hwdata==32'hffffffff) $display("COVER data/ones");
                                if(ds==2 && hwdata==32'h55555555) $display("COVER data/alternating");
                            end else reads=reads+1;
                            case(ds) 0:$display("COVER size/byte");1:$display("COVER size/half");2:$display("COVER size/word");endcase
                            if(recovering) begin $display("COVER reset/recovery");recovering=0;end
                        end
                        age=0;first_error=0;
                    end
                end
                if(hready && hsel && htrans[1]) begin
                    accepted=accepted+1;
`ifdef BUS_VALIDATION
                    if(perf_start<0) perf_start=checks;
`endif
                    if(htrans==2) $display("COVER address/nonseq");else $display("COVER address/seq");
                    if(active) $display("COVER bus/pipeline");
                end
                if(hready && !hsel) $display("COVER bus/unselected");
                if(hready && hsel && htrans==0) $display("COVER bus/idle");
                if(hready && hsel && htrans==1) $display("COVER bus/busy");
            end
            @(posedge hclk);#1;
            for(integer i=0;i<4;i=i+1) if(dut.registers[i]!==expected_regs[i][31:0]) fail("AHB_STATE");
            checks=checks+1;@(negedge hclk);
        end
        $fclose(fd);
        $display("COUNT accepted=%0d",accepted);$display("COUNT reads=%0d",reads);$display("COUNT writes=%0d",writes);
        $display("COUNT errors=%0d",errors);$display("COUNT waits=%0d",waits);
`ifdef BUS_VALIDATION
        $display("PERF_TOTAL ahb first=%0d last=%0d completed=%0d",perf_start,perf_last,perf_done);
`endif
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
