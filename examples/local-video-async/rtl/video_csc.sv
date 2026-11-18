// BT.601 limited-range integer approximation. Signed 32-bit intermediates.
module video_csc(
    input wire clk,reset_n,active,s_valid,output wire s_ready,input wire [57:0] s_data,
    output reg m_valid,input wire m_ready,output reg [57:0] m_data
);
    function automatic [7:0] sat8(input integer value);
        if (value<0) sat8=0;
        else if (value>255) sat8=255;
        else sat8=8'(value);
    endfunction
    function automatic [23:0] convert(input [23:0] ycc);
        integer c,d,e,r,g,b;
        begin
            c=int'({1'b0,ycc[23:16]})-16;
            d=int'({1'b0,ycc[15:8]})-128;
            e=int'({1'b0,ycc[7:0]})-128;
            r=(298*c+409*e+128)>>>8;
            g=(298*c-100*d-208*e+128)>>>8;
            b=(298*c+516*d+128)>>>8;
            convert={sat8(r),sat8(g),sat8(b)};
        end
    endfunction
    assign s_ready=active && (!m_valid || m_ready);
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin m_valid<=0; m_data<=0; end
        else if (active && (!m_valid || m_ready)) begin
            m_valid<=s_valid;
            if (s_valid) m_data<={s_data[57:56],convert(s_data[55:32]),s_data[31:0]};
        end
    end
endmodule
