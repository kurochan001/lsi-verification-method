interface rx_if(input bit clk);
  logic rst_n;
  logic cmd_valid, cmd_write, cmd_ready;
  logic [7:0] cmd_addr, cmd_wdata;
  logic req_valid, req_write, req_ready;
  logic [7:0] req_addr, req_wdata;
  logic rsp_valid, rsp_err;
  logic [7:0] rsp_rdata;
  logic done_valid, done_err, done_timeout;
  logic [7:0] done_rdata;
  logic [1:0] done_tries;
endinterface
