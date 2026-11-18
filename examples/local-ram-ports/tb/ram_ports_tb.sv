`timescale 1ns/1ps
module ram_ports_tb;
    parameter DATA_W=32,DEPTH=16,ADDR_W=16,BASE_ADDR=256,KIND=2,RDW_MODE=0,MUTATION=0;
    reg clk=0,rst_n=0,a_valid=0,a_write=0,a_word=0,b_valid=0,b_write=0,b_word=0;
    reg [ADDR_W-1:0] a_addr=0,b_addr=0;
    reg [DATA_W-1:0] a_wdata=0,b_wdata=0;
    reg [DATA_W/8-1:0] a_strb=0,b_strb=0;
    wire a_ready,b_ready,a_rsp_valid,b_rsp_valid,a_error,b_error,write_collision,a_read_collision,b_read_collision;
    wire [DATA_W-1:0] a_rdata,b_rdata;
    ram_ports_top #(.DATA_W(DATA_W),.DEPTH(DEPTH),.ADDR_W(ADDR_W),.BASE_ADDR(BASE_ADDR),
        .KIND(KIND),.RDW_MODE(RDW_MODE),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    // rst; six request fields for A and B; seven response flags; two data words; phase.
    localparam FIELD_W=DATA_W>ADDR_W ? DATA_W:ADDR_W;
    reg [FIELD_W-1:0] v[0:22];
    integer fd,rc,rows=0,checks,reads=0,writes=0,errors=0,collisions=0,resets=0;
    reg old_rst=0,recovering=0;
    reg [DATA_W-1:0] previous_a=0,previous_b=0;
    reg [6:0] previous_flags=0;
    integer phase=0;
    reg [31:0] seed=17;
    string vectors,wave,test_name="ram";
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s",label);
            $display("test=%s seed=%0d row=%0d phase=%0d kind=%0d width=%0d depth=%0d rdw_mode=%0d mutation=%0d",test_name,seed,rows,phase,KIND,DATA_W,DEPTH,RDW_MODE,MUTATION);
            $display("port=A valid=%b write=%b word_mode=%b address=%h data=%h mask=%h expected=%h actual=%h",a_valid,a_write,a_word,a_addr,a_wdata,a_strb,v[20],a_rdata);
            $display("port=B valid=%b write=%b word_mode=%b address=%h data=%h mask=%h expected=%h actual=%h",b_valid,b_write,b_word,b_addr,b_wdata,b_strb,v[21],b_rdata);
            $display("actual_flags=%b%b%b%b%b%b%b expected_flags=%b%b%b%b%b%b%b",a_rsp_valid,b_rsp_valid,a_error,b_error,write_collision,a_read_collision,b_read_collision,v[13][0],v[14][0],v[15][0],v[16][0],v[17][0],v[18][0],v[19][0]);
            $fatal(1,"RAM contract mismatch");
        end
    endtask
    task cover_access(input logic valid,write,word_mode,error,input [ADDR_W-1:0] address,input [DATA_W/8-1:0] mask);
        integer index_value;
        begin
            if (valid) begin
                if (word_mode) $display("COVER address/word");else $display("COVER address/byte");
                if (!word_mode && (32'(address)-BASE_ADDR)%(DATA_W/8)!=0 && error) $display("COVER address/misaligned");
                if (error && (word_mode ? 32'(address)>=DEPTH : 32'(address)<BASE_ADDR || 32'(address)>=BASE_ADDR+DEPTH*(DATA_W/8))) $display("COVER address/range");
                if (!error) begin
                    index_value=word_mode ? int'(address):(int'(address)-BASE_ADDR)/(DATA_W/8);
                    if (index_value==0) $display("COVER bounds/first");
                    if (index_value==DEPTH-1) $display("COVER bounds/last");
                    if (write) begin
                        writes=writes+1;$display("COVER access/write");
                        if (mask==0) $display("COVER data/zero-mask");
                        else if (mask!={DATA_W/8{1'b1}}) $display("COVER data/partial");
                    end else begin
                        reads=reads+1;$display("COVER access/read");
                        $display("COVER timing/registered-response");
                        if (recovering) begin $display("COVER reset/retained");recovering=0;end
                    end
                end else errors=errors+1;
            end
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("CHECKS=%d",checks)) $fatal(1,"VECTORS and CHECKS required");
        if ($value$plusargs("SEED=%d",seed)) begin end
        if ($value$plusargs("CASE=%s",test_name)) begin end
        if ($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,ram_ports_tb);end
        fd=$fopen(vectors,"r");if (!fd) $fatal(1,"cannot open RAM vectors");
        @(negedge clk);
        while (!$feof(fd)) begin
            for (integer j=0;j<23;j=j+1) begin rc=$fscanf(fd,"%h\n",v[j]);if (rc!=1) $fatal(1,"bad RAM vector");end
            for (integer j=0;j<23;j=j+1) begin
                if ((^v[j])===1'bx) fail("RAM_INPUT");
                if ((j<=3 || j>=7 && j<=9 || j>=13 && j<=19) && v[j]>1) fail("RAM_INPUT");
            end
            if ((v[4]>>ADDR_W)!=0 || (v[10]>>ADDR_W)!=0 || (v[6]>>(DATA_W/8))!=0 || (v[12]>>(DATA_W/8))!=0 ||
                (v[5]>>DATA_W)!=0 || (v[11]>>DATA_W)!=0 || (v[20]>>DATA_W)!=0 || (v[21]>>DATA_W)!=0) fail("RAM_INPUT");
            rst_n=v[0][0];
            a_valid=v[1][0];a_write=v[2][0];a_word=v[3][0];a_addr=ADDR_W'(v[4]);a_wdata=v[5];a_strb=(DATA_W/8)'(v[6]);
            b_valid=v[7][0];b_write=v[8][0];b_word=v[9][0];b_addr=ADDR_W'(v[10]);b_wdata=v[11];b_strb=(DATA_W/8)'(v[12]);
            phase=int'(v[22]);
            if (old_rst && !rst_n) begin resets=resets+1;recovering=1;end
            old_rst=rst_n;
            #1;
            if ({a_ready,b_ready}!=={rst_n,rst_n}) fail("RAM_READY");
            if (a_rdata!==previous_a || b_rdata!==previous_b ||
                {a_rsp_valid,b_rsp_valid,a_error,b_error,write_collision,a_read_collision,b_read_collision}!==previous_flags) fail("RAM_LATENCY");
            @(posedge clk);#1;
            if ({a_rsp_valid,b_rsp_valid,a_error,b_error,write_collision,a_read_collision,b_read_collision}!==
                {v[13][0],v[14][0],v[15][0],v[16][0],v[17][0],v[18][0],v[19][0]}) fail("RAM_STATUS");
            if (a_rdata!==v[20] || b_rdata!==v[21]) fail("RAM_DATA");
            if (rst_n) begin
                cover_access(a_valid,a_write,a_word,a_error,a_addr,a_strb);
                cover_access(b_valid,b_write,b_word,b_error,b_addr,b_strb);
                if (!a_valid && !b_valid) $display("COVER timing/idle-hold");
                if (KIND<2 && (b_valid && (KIND==0 || b_write) || KIND==1 && a_valid && !a_write)) $display("COVER port/rejected");
                if (a_read_collision || b_read_collision) begin
                    $display("COVER collision/read-write");
                    if (RDW_MODE==0) $display("COVER rdw/read-first");
                    if (RDW_MODE==1) $display("COVER rdw/write-first");
                    if (RDW_MODE==2) $display("COVER rdw/no-change");
                end
                if (write_collision) begin collisions=collisions+1;$display("COVER collision/write-reject");end
                if (a_valid && b_valid && !a_error && !b_error) begin
                    if (!a_write && !b_write) $display("COVER concurrent/two-read");
                    else if (a_write && b_write && a_strb!=0 && b_strb!=0) $display("COVER concurrent/two-write");
                    else if (a_write!=b_write &&
                        (a_word ? int'(a_addr):(int'(a_addr)-BASE_ADDR)/(DATA_W/8))!=
                        (b_word ? int'(b_addr):(int'(b_addr)-BASE_ADDR)/(DATA_W/8))) $display("COVER concurrent/read-write");
                end
            end
            previous_a=a_rdata;previous_b=b_rdata;
            previous_flags={a_rsp_valid,b_rsp_valid,a_error,b_error,write_collision,a_read_collision,b_read_collision};
            rows=rows+1;@(negedge clk);
        end
        if (rows!=checks || rows==0) fail("RAM_COMPLETION");
        $display("COUNT rows=%0d",rows);$display("COUNT reads=%0d",reads);$display("COUNT writes=%0d",writes);
        $display("COUNT errors=%0d",errors);$display("COUNT collisions=%0d",collisions);$display("COUNT resets=%0d",resets);
        $display("RESULT PASS checks=%0d",rows);$fclose(fd);$finish;
    end
    initial begin #10000000;$fatal(1,"RAM watchdog expired");end
endmodule
