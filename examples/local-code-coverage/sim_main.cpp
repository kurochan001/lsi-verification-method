#include "Vcommand_unit.h"
#include "verilated.h"
#include "verilated_cov.h"
#include "verilated_vcd_c.h"
#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <vector>
int main(int argc,char**argv){
 if(argc!=3)return 2;
 std::ifstream input(argv[1]);if(!input)return 2;
 std::vector<std::array<uint64_t,12>> rows;std::string line;
 while(std::getline(input,line)){
  std::istringstream stream(line);std::array<uint64_t,12> row{};uint64_t extra;
  for(auto& value:row)if(!(stream>>std::hex>>value))return 2;
  if(stream>>extra)return 2;rows.push_back(row);
 }
 if(rows.empty())return 2;
 auto context=std::make_unique<VerilatedContext>();context->commandArgs(argc,argv);context->traceEverOn(true);
 auto top=std::make_unique<Vcommand_unit>(context.get());
 auto trace=std::make_unique<VerilatedVcdC>();top->trace(trace.get(),5);trace->open(argv[2]);
 auto eval=[&](){top->eval();trace->dump(context->time());context->timeInc(5);};
 auto edge=[&](){top->clk=1;eval();top->clk=0;eval();};
 top->rst_n=0;top->clk=0;top->req_valid=0;top->operation=0;top->enable=0;top->authorized=0;
 top->a=0;top->b=0;top->resp_ready=0;eval();edge();edge();
#if VM_COVERAGE
 context->coveragep()->zero();
#endif
 size_t checks=0,failures=0;std::string label;
 for(const auto& r:rows){
  top->rst_n=r[0];top->req_valid=r[1];top->operation=r[2];top->a=r[3];top->b=r[4];
  top->enable=r[5];top->authorized=r[6];top->resp_ready=r[7];eval();
  std::string current;
  if(top->req_ready!=r[8] || top->resp_valid!=r[9])current="CODE_FLOW";
  else if(top->resp_valid && (top->result!=r[10] || top->error!=r[11]))current="CODE_DATA";
  if(!current.empty()){if(label.empty() || current=="CODE_FLOW")label=current;++failures;}
  edge();++checks;
 }
 top->final();trace->close();
#if VM_COVERAGE
 context->coveragep()->write("coverage.dat");
#endif
 std::cout<<"COUNT steps="<<checks<<"\n";
 if(failures){std::cout<<"CHECK_FAIL "<<label<<"\nRESULT FAIL checks="<<checks<<" failures="<<failures<<"\n";return 1;}
 std::cout<<"RESULT PASS checks="<<checks<<"\n";return 0;
}
