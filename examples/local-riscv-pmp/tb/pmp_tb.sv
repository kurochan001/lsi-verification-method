`timescale 1ns/1ps
module pmp_tb;
    parameter AW=16,MUTATION=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_we=0,addr_we=0,machine=0;
    reg [1:0] index=0,size_log2=0,kind=0;
    reg [31:0] wdata=0;
    reg [AW-1:0] address=0;
    wire allow;wire [2:0] matched;
    wire [31:0] configs;wire [4*(AW-2)-1:0] addresses;
    pmp #(.AW(AW),.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0;reg [63:0] v[0:12];string vectors,wave;
    reg [7:0] selected;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,pmp_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");
        repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12]);
            if(n!=13)$fatal(1,"bad row");
            rst_n=v[0][0];cfg_we=v[1][0];addr_we=v[2][0];index=v[3][1:0];wdata=v[4][31:0];
            address=v[5][AW-1:0];size_log2=v[6][1:0];kind=v[7][1:0];machine=v[8][0];#1;
            if(allow!==v[9][0] || matched!==v[10][2:0])fail("PMP_DECISION");
            if(configs!==v[11][31:0] || addresses!==v[12][4*(AW-2)-1:0])fail("PMP_STATE");
            selected=0;if(matched<4)selected=configs[8*matched+:8];
            if(rst_n && !cfg_we && !addr_we)begin
                if(matched==4 && !machine && !allow)$display("COVER match/unmapped-user");
                if(matched==4 && machine && allow)$display("COVER match/unmapped-machine");
                if(matched<4)begin
                    case(selected[4:3])
                        1:$display("COVER mode/tor");2:$display("COVER mode/na4");3:$display("COVER mode/napot");
                        default:begin end
                    endcase
                    if(machine && !selected[7] && allow)$display("COVER privilege/machine-bypass");
                    if(machine && selected[7] && !allow)$display("COVER privilege/locked-machine-deny");
                    if(matched==0 && configs[20:19]==3)$display("COVER match/priority");
                end
                if(allow)case(kind)
                    0:$display("COVER allow/read");1:$display("COVER allow/write");2:$display("COVER allow/execute");default:begin end
                endcase
                if(!allow && address==AW'('hfe) && size_log2==2)$display("COVER deny/partial");
                if(!allow && (&address) && size_log2==2)$display("COVER deny/physical-wrap");
            end
            if(rst_n && addr_we && index==2 && configs[31] && configs[28:27]==1)$display("COVER lock/tor-predecessor");
            if(rst_n && (addr_we || cfg_we) && configs[8*index+7])$display("COVER lock/entry");
            if(!rst_n && checks>2)$display("COVER reset/reconfigure");
            @(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
