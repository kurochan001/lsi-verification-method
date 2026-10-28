module cdc_handshake #(parameter SYNC_STAGES=2, MUTATION=0)(
    input wire src_clk, dst_clk, rst_n,
    input wire src_valid,
    input wire [7:0] src_data,
    output wire src_ready,
    input wire dst_ready,
    output wire dst_valid,
    output wire [7:0] dst_data,
    input wire src_pulse,
    output wire dst_pulse,
    output wire dst_rst_n
);
    localparam S=SYNC_STAGES;
    reg req;
    reg [7:0] data_reg;
    reg [S-1:0] req_sync;
    reg ack;
    reg [S-1:0] ack_sync;
    reg [S-1:0] rst_sync;
    reg toggle;
    reg [S-1:0] pulse_sync;
    reg pulse_prev;

    assign dst_rst_n = MUTATION == 4 ? rst_n : rst_sync[S-1];
    assign src_ready = rst_n && !req && !ack_sync[S-1];
    assign dst_valid = dst_rst_n && req_sync[S-1] && !ack;
    assign dst_data = MUTATION == 1 ? (data_reg ^ 8'h01) : data_reg;
    assign dst_pulse = dst_rst_n && (MUTATION == 3 ? 1'b1 :
                                     (pulse_sync[S-1] ^ pulse_prev));

    always @(posedge dst_clk or negedge rst_n) begin
        if (!rst_n) rst_sync <= 0;
        else rst_sync <= {rst_sync[S-2:0], 1'b1};
    end

    always @(posedge src_clk or negedge rst_n) begin
        if (!rst_n) begin
            req <= 0; data_reg <= 0; ack_sync <= 0; toggle <= 0;
        end else begin
            ack_sync <= {ack_sync[S-2:0], ack};
            if (ack_sync[S-1]) req <= 0;
            if (src_valid && src_ready) begin
                req <= 1; data_reg <= src_data;
            end
            if (src_pulse) toggle <= ~toggle;
        end
    end

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            req_sync <= 0; ack <= 0; pulse_sync <= 0; pulse_prev <= 0;
        end else begin
            req_sync <= {req_sync[S-2:0], req};
            pulse_sync <= {pulse_sync[S-2:0], toggle};
            pulse_prev <= pulse_sync[S-1];
            if (dst_valid && dst_ready) ack <= 1;
            if (MUTATION != 2 && !req_sync[S-1]) ack <= 0;
        end
    end
endmodule
