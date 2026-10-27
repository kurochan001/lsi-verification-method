// Teaching specification: independent timer IRQ and watchdog reset request.
module timer_watchdog #(parameter WIDTH=4, MUTATION=0)(
    input wire clk, rst_n,
    input wire timer_enable, periodic, timer_load,
    input wire [WIDTH-1:0] timer_reload,
    input wire watchdog_enable, watchdog_load,
    input wire [WIDTH-1:0] watchdog_reload,
    input wire kick, clear_irq,
    output reg [WIDTH-1:0] timer_count, watchdog_count,
    output reg irq, watchdog_reset_request, timer_expired
);
    reg [WIDTH-1:0] timer_saved, watchdog_saved;
    always @(posedge clk) begin
        if (!rst_n) begin
            timer_count<=0; watchdog_count<=0;
            timer_saved<=0; watchdog_saved<=0;
            irq<=0; watchdog_reset_request<=0; timer_expired<=0;
        end else begin
            timer_expired<=0;
            watchdog_reset_request<=0;
            if (clear_irq) irq<=0;
            if (timer_load) begin
                timer_saved<=timer_reload;
                timer_count<=timer_reload;
            end else if (timer_enable && timer_count!=0) begin
                if (timer_count==1 || (MUTATION==1 && timer_count==2)) begin
                    timer_expired<=1;
                    irq<=1;
                    timer_count<=(periodic && MUTATION!=4) ? timer_saved : 0;
                end else timer_count<=timer_count-1'b1;
            end
            // Intentional fault: clear incorrectly wins over a simultaneous event.
            if (MUTATION==2 && clear_irq) irq<=0;
            if (watchdog_load) begin
                watchdog_saved<=watchdog_reload;
                watchdog_count<=watchdog_reload;
            end else if (watchdog_enable) begin
                if (kick && MUTATION!=3) watchdog_count<=watchdog_saved;
                else if (watchdog_count!=0) begin
                    watchdog_count<=watchdog_count-1'b1;
                    if (watchdog_count==1) watchdog_reset_request<=1;
                end
            end
        end
    end
endmodule
