// Top-K selector for N signed 8-bit scores with one output register. An odd-even
// transposition network of N stages sorts (score, index) pairs: higher score first,
// and the lower index first when scores are equal. The first K pairs are registered.
module topk_select #(parameter N=4, K=2, MUTATION=0)(
    input wire clk, rst_n,
    input wire in_valid, input wire [8*N-1:0] in_scores,
    output reg out_valid, output reg [8*K-1:0] out_scores, output reg [$clog2(N)*K-1:0] out_index);
    localparam IW = $clog2(N);
    // The last stage that compares positions K-1 and K (the edge of the selected set).
    localparam EDGE_STAGE = (N-1) % 2 == (K-1) % 2 ? N-1 : N-2;
    reg signed [7:0] score [0:N-1];
    reg [IW-1:0] index [0:N-1];
    reg signed [7:0] held_score;
    reg [IW-1:0] held_index;
    reg swap;
    integer stage, i;
    always @* begin
        for (i = 0; i < N; i = i + 1) begin
            score[i] = in_scores[8*i +: 8];
            index[i] = i;
        end
        for (stage = 0; stage < N; stage = stage + 1)
            for (i = stage % 2; i + 1 < N; i = i + 2)
                if (!(MUTATION == 2 && stage == EDGE_STAGE && i == K-1)) begin
                    if (MUTATION == 1) swap = score[i+1] >= score[i];
                    else if (MUTATION == 4) swap = $unsigned(score[i+1]) > $unsigned(score[i]) ||
                                                   (score[i+1] == score[i] && index[i+1] < index[i]);
                    else swap = score[i+1] > score[i] || (score[i+1] == score[i] && index[i+1] < index[i]);
                    if (swap) begin
                        held_score = score[i]; score[i] = score[i+1]; score[i+1] = held_score;
                        if (MUTATION != 3) begin
                            held_index = index[i]; index[i] = index[i+1]; index[i+1] = held_index;
                        end
                    end
                end
    end
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 0; out_scores <= 0; out_index <= 0;
        end else begin
            out_valid <= in_valid;
            for (i = 0; i < K; i = i + 1) begin
                out_scores[8*i +: 8] <= score[i];
                out_index[IW*i +: IW] <= index[i];
            end
        end
    end
endmodule
