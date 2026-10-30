// Formal harness: the scores of the previous edge are kept beside the DUT, and every
// registered result is checked against them for all 2^(8N) score vectors.
module topk_formal #(parameter N=4, K=2, MUTATION=0)(
    input wire clk, rst_n, in_valid, input wire [8*N-1:0] in_scores);
    localparam IW = $clog2(N);
    wire out_valid;
    wire [8*K-1:0] out_scores;
    wire [IW*K-1:0] out_index;
    topk_select #(.N(N), .K(K), .MUTATION(MUTATION)) dut(.*);
    reg past_valid = 0, snap_valid = 0;
    reg [8*N-1:0] snap = 0;
    always @(posedge clk) begin
        past_valid <= 1;
        snap <= in_scores;
        snap_valid <= rst_n && in_valid;
    end
    function signed [7:0] input_score(input integer j);
        input_score = snap[8*j +: 8];
    endfunction
    function signed [7:0] output_score(input integer i);
        output_score = out_scores[8*i +: 8];
    endfunction
    function [IW-1:0] output_index(input integer i);
        output_index = out_index[IW*i +: IW];
    endfunction
    // index: each output is the input at its reported index; distinct: no input twice;
    // sorted / ties: descending, lower index first on equal scores; topk: every input
    // left out ranks below the K-th output under the same order.
    reg index_ok, distinct, sorted, ties, topk, selected, all_equal, all_negative, boundary_tie, ascending;
    integer i, j;
    always @* begin
        index_ok = 1; distinct = 1; sorted = 1; ties = 1; topk = 1;
        all_equal = 1; all_negative = 1; boundary_tie = 0; ascending = 1;
        for (i = 0; i < K; i = i + 1) begin
            if (output_score(i) != input_score(output_index(i))) index_ok = 0;
            for (j = i + 1; j < K; j = j + 1) if (output_index(i) == output_index(j)) distinct = 0;
            if (i + 1 < K && output_score(i) < output_score(i+1)) sorted = 0;
            if (i + 1 < K && output_score(i) == output_score(i+1) && output_index(i) > output_index(i+1)) ties = 0;
        end
        for (j = 0; j < N; j = j + 1) begin
            selected = 0;
            for (i = 0; i < K; i = i + 1) if (output_index(i) == j) selected = 1;
            if (!selected && (input_score(j) > output_score(K-1) ||
                              (input_score(j) == output_score(K-1) && j < output_index(K-1)))) topk = 0;
            if (!selected && input_score(j) == output_score(K-1)) boundary_tie = 1;
            if (input_score(j) != input_score(0)) all_equal = 0;
            if (input_score(j) >= 0) all_negative = 0;
            if (j + 1 < N && input_score(j) >= input_score(j+1)) ascending = 0;
        end
    end
    always @(posedge clk) begin
        if (!past_valid) as_initial_reset: assume(!rst_n);
        if (past_valid) begin
            ap_valid: assert(out_valid == snap_valid);
            if (out_valid) begin
                ap_index: assert(index_ok);
                ap_distinct: assert(distinct);
                ap_sorted: assert(sorted);
                ap_ties: assert(ties);
                ap_topk: assert(topk);
            end
            cp_all_equal: cover(out_valid && all_equal);
            cp_boundary_tie: cover(out_valid && boundary_tie);
            cp_all_negative: cover(out_valid && all_negative);
            cp_ascending: cover(out_valid && ascending);
            cp_max_last: cover(out_valid && output_index(0) == N-1 && !all_equal);
            cp_min_selected: cover(out_valid && output_score(K-1) == -128 && !all_equal);
        end
    end
endmodule
