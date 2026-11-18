// Packet: {sof,eol,y[7:0],cb[7:0],cr[7:0],alpha[7:0],background_rgb[23:0]}.
module video_key #(parameter [23:0] KEY=24'h51905a)(
    input wire clk,reset_n,active,s_valid,output wire s_ready,input wire [57:0] s_data,
    output reg m_valid,input wire m_ready,output reg [57:0] m_data
);
    assign s_ready=active && (!m_valid || m_ready);
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin m_valid<=0; m_data<=0; end
        else if (active && (!m_valid || m_ready)) begin
            m_valid<=s_valid;
            if (s_valid) m_data<={s_data[57:32],s_data[55:32]==KEY ? 8'd0:s_data[31:24],s_data[23:0]};
        end
    end
endmodule
