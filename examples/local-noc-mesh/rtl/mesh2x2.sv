module mesh2x2 #(parameter BUF = 1, MUTATION = 0) (
    input wire clk, rst_n,
    input wire [3:0] inject_valid,
    input wire [11:0] inject_flit,
    input wire [3:0] egress_ready,
    output wire [3:0] inject_ready, stall, err_rst,
    output wire [3:0] egress_valid,
    output wire [47:0] egress_pkt        // {node3,node2,node1,node0}×12ビット
);
    wire [11:0] e_pkt [0:3], w_pkt [0:3];
    wire e_valid [0:3], w_valid [0:3];
    wire loc_ready [0:3], e_ready [0:3], w_ready [0:3];
    wire e_out_ready [0:3], w_out_ready [0:3];
    wire [11:0] e_out [0:3], w_out [0:3], loc_out [0:3];
    wire e_outv [0:3], w_outv [0:3], loc_outv [0:3];
    wire [2:0] full [0:3];
    wire [2:1] pending_out [0:3];

    genvar n;
    generate
        for (n = 0; n < 4; n = n + 1) begin : g_rt
            router #(.ID(n), .BUF(BUF), .MUTATION(MUTATION)) rt (
                .clk(clk), .rst_n(rst_n),
                .loc_pkt(inject_flit), .e_pkt(e_pkt[n]), .w_pkt(w_pkt[n]),
                .loc_valid(inject_valid[n]), .e_valid(e_valid[n]), .w_valid(w_valid[n]),
                .loc_out_ready(egress_ready[n]), .e_out_ready(e_out_ready[n]),
                .w_out_ready(w_out_ready[n]),
                .loc_ready(loc_ready[n]), .e_ready(e_ready[n]), .w_ready(w_ready[n]),
                .loc_out_pkt(loc_out[n]), .e_out_pkt(e_out[n]), .w_out_pkt(w_out[n]),
                .loc_out_valid(loc_outv[n]), .e_out_valid(e_outv[n]), .w_out_valid(w_outv[n]),
                .pending_out(pending_out[n]));
        end
    endgenerate

    // XY配線。東出力(+x)はn+1、北出力(+y)はn+2へ。端の未使用ポートは1'b1で開く。
    assign e_valid[1] = e_outv[0];   assign e_pkt[1] = e_out[0];
    assign e_valid[3] = e_outv[2];   assign e_pkt[3] = e_out[2];
    assign e_valid[0] = 1'b0;        assign e_pkt[0] = 12'd0;
    assign e_valid[2] = 1'b0;        assign e_pkt[2] = 12'd0;
    assign w_valid[2] = w_outv[0];   assign w_pkt[2] = w_out[0];
    assign w_valid[3] = w_outv[1];   assign w_pkt[3] = w_out[1];
    assign w_valid[0] = 1'b0;        assign w_pkt[0] = 12'd0;
    assign w_valid[1] = 1'b0;        assign w_pkt[1] = 12'd0;
    assign e_out_ready[0] = ~full[1][1];
    assign e_out_ready[2] = ~full[3][1];
    assign e_out_ready[1] = 1'b1;
    assign e_out_ready[3] = 1'b1;
    assign w_out_ready[0] = ~full[2][2];
    assign w_out_ready[1] = ~full[3][2];
    assign w_out_ready[2] = 1'b1;
    assign w_out_ready[3] = 1'b1;

    assign full[0] = {~w_ready[0], ~e_ready[0], ~loc_ready[0]};
    assign full[1] = {~w_ready[1], ~e_ready[1], ~loc_ready[1]};
    assign full[2] = {~w_ready[2], ~e_ready[2], ~loc_ready[2]};
    assign full[3] = {~w_ready[3], ~e_ready[3], ~loc_ready[3]};

    assign inject_ready = {loc_ready[3], loc_ready[2], loc_ready[1], loc_ready[0]};
    assign stall[0] = 0;
    assign stall[1] = pending_out[0][1] && !e_ready[1];
    assign stall[2] = pending_out[0][2] && !w_ready[2];
    assign stall[3] = (pending_out[1][2] && !w_ready[3]) || (pending_out[2][1] && !e_ready[3]);
    assign err_rst = {4{!rst_n}};
    assign egress_valid = {loc_outv[3], loc_outv[2], loc_outv[1], loc_outv[0]};
    assign egress_pkt = {loc_out[3], loc_out[2], loc_out[1], loc_out[0]};
endmodule
