// APB3 subset wrapper around the existing timer/watchdog teaching core.
module apb_timer #(parameter WIDTH=4,WAIT_CYCLES=0,MUTATION=0)(
    input wire clk,rst_n,psel,penable,pwrite,
    input wire [7:0] paddr,
    input wire [31:0] pwdata,
    output wire pready,pslverr,
    output reg [31:0] prdata,
    output wire irq,watchdog_reset_request,timer_expired,
    output wire [WIDTH-1:0] timer_count,watchdog_count
);
    reg [3:0] control;
    reg [WIDTH-1:0] timer_reload,watchdog_reload;
    integer remaining;
    wire pending;
    wire known=paddr==0 || paddr==4 || paddr==8 || paddr==12 || paddr==16 || paddr==20 || paddr==24 || paddr==28;
    wire writable=paddr==0 || paddr==4 || paddr==8 || paddr==12;
    wire bad=!known || (pwrite && !writable);
    assign pready=rst_n && psel && penable && remaining==0;
    assign pslverr=pready && bad;
    wire commit=pready && pwrite && !bad;
    wire command=(MUTATION==3 ? rst_n && psel && pwrite : commit) && paddr==12;
    assign irq=pending && (control[3] || MUTATION==4);
    timer_watchdog #(.WIDTH(WIDTH),.MUTATION(MUTATION==2 ? 2 : 0)) core(
        .clk(clk),.rst_n(rst_n),.timer_enable(control[0]),.periodic(control[1]),
        .timer_load(command && pwdata[0]),.timer_reload(timer_reload),
        .watchdog_enable(control[2]),.watchdog_load(command && pwdata[1]),
        .watchdog_reload(watchdog_reload),.kick(command && pwdata[2]),
        .clear_irq(command && pwdata[3]),.timer_count(timer_count),.watchdog_count(watchdog_count),
        .irq(pending),.watchdog_reset_request(watchdog_reset_request),.timer_expired(timer_expired));
    always @* begin
        prdata=0;
        case(paddr)
            0:prdata={28'b0,control};
            4:prdata=timer_reload;
            8:prdata=watchdog_reload;
            12:prdata=0;
            16:prdata={29'b0,watchdog_reset_request,timer_expired,pending};
            20:prdata=timer_count;
            24:prdata=watchdog_count;
            28:prdata=32'h54494d52;
            default:prdata=0;
        endcase
    end
    always @(posedge clk) begin
        if(!rst_n) begin control<=0;timer_reload<=0;watchdog_reload<=0;remaining<=0;end
        else begin
            if(psel && !penable) remaining<=WAIT_CYCLES;
            else if(psel && penable && remaining>0) remaining<=remaining-1;
            if(commit) case(paddr)
                0:control<=pwdata[3:0];
                4:timer_reload<=pwdata[WIDTH-1:0];
                8:watchdog_reload<=pwdata[WIDTH-1:0];
                default:begin end
            endcase
            if(MUTATION==1 && psel && !penable && pwrite && paddr==0) control<=pwdata[3:0];
        end
    end
endmodule
