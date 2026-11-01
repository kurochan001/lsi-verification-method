// Bounded Ethernet II / ARP / IPv4-UDP decoder and canonical echo reply builder.
// Byte zero is DA[47:40]; FCS is reflected CRC-32, low CRC byte first.
module packet_codec #(parameter MAX_FRAME=128,MUTATION=0,
    parameter [47:0] LOCAL_MAC=48'h020000000001,
    parameter [31:0] LOCAL_IP=32'hc0000201,parameter [15:0] UDP_PORT=16'd1234)(
    input wire valid,input wire [8*MAX_FRAME-1:0] frame_data,input wire [15:0] frame_length,input wire frame_error,
    output reg accept,output reg [1:0] kind,output reg [3:0] drop_reason,
    output reg [8*MAX_FRAME-1:0] reply_data,output reg [15:0] reply_length
);
    function automatic [7:0] octet(input [8*MAX_FRAME-1:0] data,input integer offset);
        octet=data[8*offset+:8];
    endfunction
    function automatic [15:0] word16(input [8*MAX_FRAME-1:0] data,input integer offset);
        word16={octet(data,offset),octet(data,offset+1)};
    endfunction
    function automatic [31:0] word32(input [8*MAX_FRAME-1:0] data,input integer offset);
        word32={word16(data,offset),word16(data,offset+2)};
    endfunction
    function automatic [47:0] mac(input [8*MAX_FRAME-1:0] data,input integer offset);
        mac={word16(data,offset),word32(data,offset+2)};
    endfunction
    function automatic [31:0] crc32(input [8*MAX_FRAME-1:0] data,input integer length);
        reg [31:0] value;
        begin
            value=32'hffffffff;
            for(integer i=0;i<MAX_FRAME;i=i+1)if(i<length)begin
                value=value^{24'd0,octet(data,i)};
                for(integer j=0;j<8;j=j+1)value=(value>>1)^(value[0] ? 32'hedb88320 : 32'd0);
            end
            crc32=~value;
        end
    endfunction
    function automatic [15:0] folded(input [31:0] sum);
        reg [31:0] value;
        begin value={16'd0,sum[15:0]}+{16'd0,sum[31:16]};value={16'd0,value[15:0]}+{16'd0,value[31:16]};folded=value[15:0];end
    endfunction
    function automatic [15:0] ip_sum(input [8*MAX_FRAME-1:0] data);
        reg [31:0] value;
        begin value=0;for(integer i=0;i<10;i=i+1)value=value+{16'd0,word16(data,14+2*i)};ip_sum=folded(value);end
    endfunction
    function automatic [15:0] udp_sum(input [8*MAX_FRAME-1:0] data,input integer length);
        reg [31:0] value;reg [15:0] pair;
        begin
            value=32'd17+32'(length);
            for(integer i=0;i<4;i=i+1)value=value+{16'd0,word16(data,26+2*i)};
            for(integer i=0;i<MAX_FRAME/2;i=i+1)if(2*i<length && 34+2*i<MAX_FRAME)begin
                pair={octet(data,34+2*i),8'd0};
                if(2*i+1<length && 35+2*i<MAX_FRAME)pair[7:0]=octet(data,35+2*i);
                value=value+{16'd0,pair};
            end
            udp_sum=folded(value);
        end
    endfunction
    integer body,total,udp_length,payload,reply_body;
    reg [31:0] fcs;
    reg [15:0] checksum;
    always @* begin
        accept=0;kind=0;drop_reason=0;reply_data=0;reply_length=0;
        body=int'(frame_length)-4;total=int'(word16(frame_data,16));udp_length=int'(word16(frame_data,38));
        payload=udp_length-8;reply_body=60;fcs=0;checksum=0;
        if(valid)begin
            if(frame_error)drop_reason=3;
            else if(frame_length<64 || int'(frame_length)>MAX_FRAME)drop_reason=2;
            else if(MUTATION!=1 && crc32(frame_data,body)!=={octet(frame_data,body+3),octet(frame_data,body+2),octet(frame_data,body+1),octet(frame_data,body)})drop_reason=1;
            else if(mac(frame_data,0)!=LOCAL_MAC && !(word16(frame_data,12)==16'h0806 && mac(frame_data,0)==48'hffffffffffff))drop_reason=4;
            else if(word16(frame_data,12)==16'h0806)begin
                if(word16(frame_data,14)!=1 || word16(frame_data,16)!=16'h0800 || word16(frame_data,18)!=16'h0604 || word16(frame_data,20)!=1)drop_reason=8;
                else if(mac(frame_data,22)!=mac(frame_data,6))drop_reason=5;
                else if(word32(frame_data,38)!=LOCAL_IP)drop_reason=4;
                else begin accept=1;kind=1;end
            end else if(word16(frame_data,12)==16'h0800)begin
                if(octet(frame_data,14)!=8'h45 || (word16(frame_data,20)&16'hbfff)!=0 || octet(frame_data,23)!=17)drop_reason=8;
                else if(total<28 || total+14>body || udp_length<8 || udp_length!=total-20 || octet(frame_data,22)==0)drop_reason=5;
                else if(ip_sum(frame_data)!=16'hffff)drop_reason=6;
                else if(word32(frame_data,30)!=LOCAL_IP || word16(frame_data,36)!=UDP_PORT)drop_reason=4;
                else if(word16(frame_data,40)!=0 && udp_sum(frame_data,udp_length)!=16'hffff)drop_reason=7;
                else begin accept=1;kind=2;end
            end else drop_reason=8;
        end
        if(accept)begin
            for(integer i=0;i<6;i=i+1)begin
                reply_data[8*i+:8]=octet(frame_data,6+i);
                reply_data[8*(6+i)+:8]=LOCAL_MAC[8*(5-i)+:8];
            end
            reply_data[8*12+:16]=frame_data[8*12+:16];
            if(kind==1)begin
                reply_data[8*14+:64]=64'h0200040600080100;
                for(integer i=0;i<6;i=i+1)begin
                    reply_data[8*(22+i)+:8]=LOCAL_MAC[8*(5-i)+:8];
                    reply_data[8*(32+i)+:8]=octet(frame_data,22+i);
                end
                for(integer i=0;i<4;i=i+1)begin
                    reply_data[8*(28+i)+:8]=LOCAL_IP[8*(3-i)+:8];
                    reply_data[8*(38+i)+:8]=octet(frame_data,28+i);
                end
            end else begin
                reply_data[8*14+:8]=8'h45;
                for(integer i=16;i<22;i=i+1)reply_data[8*i+:8]=octet(frame_data,i);
                reply_data[8*22+:8]=64;reply_data[8*23+:8]=17;
                for(integer i=0;i<4;i=i+1)begin
                    reply_data[8*(26+i)+:8]=LOCAL_IP[8*(3-i)+:8];
                    reply_data[8*(30+i)+:8]=octet(frame_data,26+i);
                end
                reply_data[8*34+:16]=frame_data[8*36+:16];reply_data[8*36+:16]=frame_data[8*34+:16];
                reply_data[8*38+:16]=frame_data[8*38+:16];
                for(integer i=0;i<MAX_FRAME-42;i=i+1)if(i<payload)
                    reply_data[8*(42+i)+:8]=(MUTATION==3 && payload%2==1 && i==payload-1) ? 8'd0 : octet(frame_data,42+i);
                checksum=~ip_sum(reply_data);reply_data[8*24+:8]=checksum[15:8];reply_data[8*25+:8]=checksum[7:0];
                checksum=~udp_sum(reply_data,udp_length);if(checksum==0)checksum=16'hffff;
                if(MUTATION==2)checksum=checksum^16'd1;
                reply_data[8*40+:8]=checksum[15:8];reply_data[8*41+:8]=checksum[7:0];
                reply_body=total+14<60 ? 60 : total+14;
            end
            fcs=crc32(reply_data,reply_body);
            for(integer i=0;i<4;i=i+1)reply_data[8*(reply_body+i)+:8]=fcs[8*i+:8];
            reply_length=16'(reply_body+4);
        end
    end
endmodule
