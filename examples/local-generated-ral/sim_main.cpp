#include "Vtop.h"
#include "verilated.h"
#include <memory>
int main(int argc,char**argv){
 auto c=std::make_unique<VerilatedContext>();c->commandArgs(argc,argv);c->traceEverOn(true);
 auto top=std::make_unique<Vtop>(c.get());
 while(!c->gotFinish()){top->eval();if(c->gotFinish())break;if(!top->eventsPending())return 2;c->time(top->nextTimeSlot());}
 top->final();return 0;
}
