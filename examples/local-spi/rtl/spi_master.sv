// Teaching SPI master: eight MSB-first bits, fixed mode and clock divider.
module spi_master #(
  parameter integer CPOL=0, CPHA=0, HALF_DIV=2, MUTATION=0
) (
  input wire clk,rst_n,start,
  input wire [7:0] tx_data,
  input wire miso,
  output reg sclk,cs_n,mosi,busy,done,
  output reg [7:0] rx_data
);
  reg [7:0] tx_latched,rx_shift;
  integer ticks,edges;
  wire [7:0] payload=MUTATION==1 ? tx_data ^ 8'h01 : tx_data;
  localparam integer RELOAD=MUTATION==4 ? HALF_DIV-2 : HALF_DIV-1;
  always @(posedge clk) begin
    if(!rst_n) begin
      sclk<=CPOL;cs_n<=1;mosi<=0;busy<=0;done<=0;rx_data<=0;
      tx_latched<=0;rx_shift<=0;ticks<=0;edges<=0;
    end else begin
      done<=0;
      if(!busy) begin
        if(start) begin
          tx_latched<=payload;rx_shift<=0;mosi<=payload[7];sclk<=CPOL;
          cs_n<=0;busy<=1;ticks<=RELOAD;edges<=0;
        end
      end else if(ticks!=0) ticks<=ticks-1;
      else begin
        ticks<=RELOAD;
        if(edges<16) begin
          sclk<=!sclk;edges<=edges+1;
          if((CPHA==0 && edges%2==0) || (CPHA==1 && edges%2==1))
            rx_shift<={rx_shift[6:0],miso};
          if(CPHA==1 && edges%2==0) mosi<=tx_latched[7-edges/2];
          if(CPHA==0 && edges%2==1 && edges<15) mosi<=tx_latched[6-edges/2];
          if(MUTATION==3 && edges==0) cs_n<=1;
        end else begin
          // Hold CS for one half-period after the last SCLK edge.
          busy<=0;done<=1;cs_n<=1;sclk<=CPOL;
          rx_data<=MUTATION==2 ? rx_shift ^ 8'h01 : rx_shift;
        end
      end
    end
  end
endmodule
