// Shortened extended Hamming (13,8), even Hamming checks and overall parity.
module secded #(parameter integer MUTATION=0) (
  input wire [7:0] data_in,
  input wire [12:0] received,
  output reg [12:0] encoded, corrected_code,
  output reg [7:0] data_out,
  output reg corrected, uncorrectable
);
  reg [12:0] word;
  reg [3:0] syndrome;
  reg parity;
  integer index;
  always @* begin
    word=0;index=0;
    for(integer pos=1;pos<=12;pos=pos+1) begin
      if(pos!=1 && pos!=2 && pos!=4 && pos!=8) begin
        word[pos-1]=data_in[index];index=index+1;
      end
    end
    for(integer p=0;p<4;p=p+1) begin
      parity=0;
      for(integer pos=1;pos<=12;pos=pos+1)
        if((pos & (1<<p))!=0 && pos!=(1<<p)) parity=parity ^ word[pos-1];
      word[(1<<p)-1]=parity;
    end
    word[12]=^word[11:0];
    encoded=MUTATION==3 ? word ^ 13'h001 : word;
    syndrome=0;
    for(integer p=0;p<4;p=p+1)
      for(integer pos=1;pos<=12;pos=pos+1)
        if((pos & (1<<p))!=0) syndrome[p]=syndrome[p] ^ received[pos-1];
    corrected_code=received;corrected=0;uncorrectable=0;
    if(^received) begin
      if(syndrome==0) begin
        if(MUTATION!=1) corrected_code[12]=!received[12];
        corrected=1;
      end else if(syndrome<=12) begin
        if(MUTATION!=1) corrected_code[syndrome-1]=!received[syndrome-1];
        corrected=1;
      end else uncorrectable=1;
    end else if(syndrome!=0) uncorrectable=1;
    if(MUTATION==2) uncorrectable=0;
    if(MUTATION==4) corrected=0;
    data_out={corrected_code[11:8],corrected_code[6:4],corrected_code[2]};
  end
endmodule
