module address_map #(parameter ALIAS=1, MUTATION=0)(
    input wire clk, rst_n,
    input wire psel, pwrite,
    input wire [11:0] paddr,
    input wire [31:0] pwdata,
    input wire [3:0] pstrb,
    input wire [3:0] gpio_in,
    output reg [31:0] prdata,
    output wire pready,
    output reg pslverr,
    output wire [1:0] irq,
    output reg [3:0] gpio_out
);
    localparam RAM_REGION=0, TIMER_REGION=1, GPIO_REGION=2, ALIAS_REGION=4;
    reg [31:0] ram [0:63];
    reg [31:0] timer_ctrl, timer_match;
    reg [15:0] timer_count;
    reg [31:0] gpio_edge;
    reg [1:0] irq_bits;
    reg [3:0] gpio_in_prev;
    reg [31:0] next_count;
    wire [7:0] offset = paddr[7:0];
    wire [5:0] ram_index = paddr[7:2];
    wire aligned = paddr[1:0] == 2'b00;
    wire alias_access = paddr[11:8] == ALIAS_REGION;
    wire ram_ok = aligned && (paddr[11:8] == RAM_REGION || (ALIAS != 0 && alias_access));
    wire timer_ok = paddr[11:8] == TIMER_REGION;
    wire gpio_ok = paddr[11:8] == GPIO_REGION;
    wire known_timer = timer_ok && (offset == 8'h00 || offset == 8'h04 || offset == 8'h08 || offset == 8'h0c);
    wire known_gpio = gpio_ok && (offset == 8'h00 || offset == 8'h04 || offset == 8'h08 || offset == 8'h0c);
    wire partial = pstrb != 4'hf;
    integer i;

    always @* begin
        prdata = 0; pslverr = 0;
        if (psel) begin
            if (!aligned) pslverr = 1;
            else if (ram_ok) prdata = ram[ram_index];
            else if (timer_ok && known_timer) begin
                if (pwrite && (offset == 8'h04 || partial)) pslverr = 1;
                else case (offset)
                    8'h00: prdata = timer_ctrl;
                    8'h04: prdata = {16'b0, timer_count};
                    8'h08: prdata = timer_match;
                    8'h0c: prdata = {30'b0, irq_bits[0]};
                endcase
            end else if (gpio_ok && known_gpio) begin
                if (pwrite && (offset == 8'h04 || partial)) pslverr = 1;
                else case (offset)
                    8'h00: prdata = {28'b0, gpio_out};
                    8'h04: prdata = {28'b0, gpio_in};
                    8'h08: prdata = gpio_edge;
                    8'h0c: prdata = {30'b0, irq_bits[1]};
                endcase
            end else pslverr = MUTATION == 1 ? 0 : 1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            timer_ctrl <= 0; timer_match <= 0; timer_count <= 0;
            gpio_edge <= 0; gpio_out <= 0; gpio_in_prev <= 0; irq_bits <= 0;
            for (i = 0; i < 64; i = i + 1) ram[i] <= 0;
        end else begin
            if (psel && !pslverr && pwrite) begin
                if (ram_ok) begin
                    if (MUTATION == 2) ram[ram_index] <= pwdata;
                    else begin
                        if (pstrb[0]) ram[ram_index][7:0] <= pwdata[7:0];
                        if (pstrb[1]) ram[ram_index][15:8] <= pwdata[15:8];
                        if (pstrb[2]) ram[ram_index][23:16] <= pwdata[23:16];
                        if (pstrb[3]) ram[ram_index][31:24] <= pwdata[31:24];
                    end
                end else if (timer_ok) begin
                    case (offset)
                        8'h00: timer_ctrl <= pwdata;
                        8'h08: timer_match <= pwdata;
                        8'h0c: irq_bits[0] <= irq_bits[0] & ~pwdata[0];
                        default: begin end
                    endcase
                end else if (gpio_ok) begin
                    case (offset)
                        8'h00: gpio_out <= pwdata[3:0];
                        8'h08: gpio_edge <= pwdata;
                        8'h0c: irq_bits[1] <= irq_bits[1] & ~pwdata[0];
                        default: begin end
                    endcase
                end
            end
            next_count = {16'b0, timer_count} + 1;
            if (timer_ctrl[0]) begin
                timer_count <= next_count[15:0];
                if (next_count[15:0] == timer_match[15:0] && timer_ctrl[1]) irq_bits[0] <= 1;
            end
            if ((gpio_in & ~gpio_in_prev & gpio_edge[3:0]) != 0) irq_bits[1] <= 1;
            gpio_in_prev <= gpio_in;
            if (MUTATION == 4 && psel && pwrite && pslverr) ram[ram_index] <= pwdata;
        end
    end

    assign pready = 1'b1;
    assign irq = MUTATION == 3 ? {irq_bits[0], irq_bits[1]} : irq_bits;
endmodule
