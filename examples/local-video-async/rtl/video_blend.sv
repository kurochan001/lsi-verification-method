// Straight alpha on eight-bit code values; no gamma conversion.
module video_blend(
    input wire clk,reset_n,active,s_valid,output wire s_ready,input wire [57:0] s_data,
    output reg m_valid,input wire m_ready,output reg [25:0] m_data
);
    function automatic [7:0] blend(input [7:0] fg,bg,alpha);
        integer numerator;
        begin
            numerator=int'(alpha)*int'(fg)+(255-int'(alpha))*int'(bg)+127;
            blend=8'(numerator/255);
        end
    endfunction
    assign s_ready=active && (!m_valid || m_ready);
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin m_valid<=0; m_data<=0; end
        else if (active && (!m_valid || m_ready)) begin
            m_valid<=s_valid;
            if (s_valid) m_data<={s_data[57:56],
                blend(s_data[55:48],s_data[23:16],s_data[31:24]),
                blend(s_data[47:40],s_data[15:8],s_data[31:24]),
                blend(s_data[39:32],s_data[7:0],s_data[31:24])};
        end
    end
endmodule
