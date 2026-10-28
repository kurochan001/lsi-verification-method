module secure_lifecycle #(parameter MUTATION=0, ATTEMPT_LIMIT=3, DEBUG_KEY=16'ha55a)(
    input wire clk, rst_n,
    input wire cs, we, re,
    input wire [7:0] addr,
    input wire [31:0] wdata,
    input wire secure,
    input wire [1:0] lifecycle,
    input wire [15:0] debug_key,
    input wire tamper,
    output reg [31:0] rdata,
    output reg error,
    output reg irq
);
    localparam TEST=2'b00;
    localparam KEY0=8'h00, KEY1=8'h04, CFG=8'h08, STATUS=8'h0c;
    localparam SCRATCH=8'h10, IRQ=8'h14, LOCK=8'h18, DEBUG=8'h1c;

    reg [15:0] key0, key1;
    reg [31:0] cfg, scratch;
    reg [1:0] irq_bits;
    reg locked, debug_unlocked, tamper_latched, debug_lockout;
    reg [3:0] attempts;

    wire [7:0] index = addr;
    wire aligned = (addr[1:0] == 2'b00);
    wire known = aligned && (index == KEY0 || index == KEY1 || index == CFG || index == STATUS ||
                             index == SCRATCH || index == IRQ || index == LOCK || index == DEBUG);
    wire secure_reg = (index == KEY0 || index == KEY1 || index == CFG ||
                       index == STATUS || index == IRQ || index == LOCK || index == DEBUG);
    wire allowed_read = known && (secure || !secure_reg);
    wire write_test = (lifecycle == TEST) && !locked && !tamper_latched && !tamper;
    wire debug_available = write_test && !debug_lockout && !debug_unlocked;
    wire [31:0] status_value = {16'b0, 8'b0, attempts, debug_lockout, tamper_latched, debug_unlocked, locked};
    wire [31:0] irq_value = {30'b0, irq_bits};

    always @* begin
        rdata = 32'b0; error = 1'b0;
        if (rst_n && cs) begin
            if (re) begin
                if (!allowed_read) error = 1'b1;
                else begin
                    case (index)
                        KEY0: rdata = {16'b0, key0};
                        KEY1: rdata = {16'b0, key1};
                        CFG: rdata = cfg;
                        STATUS: rdata = status_value;
                        SCRATCH: rdata = scratch;
                        IRQ: rdata = irq_value;
                        default: rdata = 32'b0;
                    endcase
                end
            end
            if (we) begin
                if (tamper) error = 1'b1;
                else if (!known) error = 1'b1;
                else if (!secure && secure_reg && MUTATION != 1) error = 1'b1;
                else begin
                    case (index)
                        KEY0, KEY1, CFG: if (!write_test) error = 1'b1;
                        LOCK: if (!write_test) error = 1'b1;
                        DEBUG: if (!debug_available || !secure) error = 1'b1;
                        STATUS: error = 1'b1;
                        IRQ: if (!secure) error = 1'b1;
                        default: begin end
                    endcase
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            key0 <= 0; key1 <= 0; cfg <= 0; scratch <= 0; irq_bits <= 0;
            locked <= 0; debug_unlocked <= 0; tamper_latched <= 0; debug_lockout <= 0; attempts <= 0;
        end else begin
            if (tamper) begin
                if (MUTATION != 3) begin key0 <= 0; key1 <= 0; end
                tamper_latched <= 1'b1; irq_bits[0] <= 1'b1;
            end else if (cs && we) begin
                if (known && (secure || !secure_reg || MUTATION == 1)) begin
                    case (index)
                        KEY0: if (write_test) key0 <= wdata[15:0];
                        KEY1: if (write_test) key1 <= wdata[15:0];
                        CFG: if (write_test) cfg <= wdata;
                        SCRATCH: scratch <= wdata;
                        IRQ: if (secure) irq_bits <= irq_bits & ~wdata[1:0];
                        LOCK: if (write_test && wdata[0]) locked <= 1'b1;
                        DEBUG: if (debug_available && secure) begin
                            if (debug_key == DEBUG_KEY) debug_unlocked <= 1'b1;
                            else begin
                                if (attempts + 1 >= ATTEMPT_LIMIT) begin
                                    debug_lockout <= 1'b1; irq_bits[1] <= 1'b1;
                                end
                                if (MUTATION != 2 && attempts < ATTEMPT_LIMIT) attempts <= attempts + 1'b1;
                            end
                        end
                        default: begin end
                    endcase
                end
            end
            if (MUTATION == 4 && cs && we && !known) scratch <= wdata;
        end
    end

    always @* irq = rst_n && (|irq_bits);
endmodule
