#include "Vbus_model.h"
#include "verilated.h"
#include "verilated_cov.h"
#include <memory>
int main(int argc, char** argv) {
    auto context = std::make_unique<VerilatedContext>();
    context->commandArgs(argc, argv); context->traceEverOn(true);
    auto top = std::make_unique<Vbus_model>(context.get());
    while (!context->gotFinish()) {
        top->eval();
        if (context->gotFinish()) break;
        if (!top->eventsPending()) return 2;
        context->time(top->nextTimeSlot());
    }
    top->final(); VerilatedCov::write("coverage.dat"); return 0;
}
