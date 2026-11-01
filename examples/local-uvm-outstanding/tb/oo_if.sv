`timescale 1ps/1ps
interface oo_if(input bit clk);
 logic rst_n=0,release_enable=0,s_valid=0,s_ready,m_valid,m_ready=0;
 logic [1:0]s_id=0,m_id;logic [15:0]s_token=0,m_token;logic [7:0]s_data=0,m_data;
endinterface
