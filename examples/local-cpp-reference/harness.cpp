// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#include "Vdut.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "reference.hpp"
#include <deque>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

[[noreturn]] void fail(const char* label){throw std::runtime_error(label);}
void cover(const char* goal){std::cout<<"COVER "<<goal<<'\n';}
struct Pending {FirResult result;unsigned due;};
struct Test {
    VerilatedContext context;
    Vdut dut{&context};
    VerilatedVcdC wave;
    std::ofstream csv;
    FirReference model;
    std::deque<Pending> queue;
    unsigned cycle=0,accepted=0,retired=0,cancelled=0,resets=0;
    bool held=false,after_reset=false,history_live=false;
    int held_data=0;
    Test(const char* vcd,const char* path,bool faulty):csv(path),model(CFG_WIDTH,faulty){
        if(!csv)fail("CPP_TRACE");
        context.traceEverOn(true);dut.trace(&wave,99);wave.open(vcd);
        csv<<"cycle,reset_n,input_valid,input_ready,input,output_valid,output_ready,output,queued\n";
    }
    ~Test(){dut.final();wave.close();}
    int signed_value(unsigned x)const{return int(x^(1u<<(CFG_WIDTH-1)))-int(1u<<(CFG_WIDTH-1));}
    bool tick(bool resetn,bool valid,int sample,bool ready){
        dut.clk=0;dut.rst_n=resetn;dut.in_valid=valid;dut.in_sample=std::uint32_t(sample)&((1u<<CFG_WIDTH)-1);dut.out_ready=ready;dut.eval();
        wave.dump(context.time());context.timeInc(5);
        const int data=signed_value(dut.out_sample);
        csv<<cycle<<','<<resetn<<','<<valid<<','<<unsigned(dut.in_ready)<<','<<sample<<','<<unsigned(dut.out_valid)<<','<<ready<<','<<data<<','<<queue.size()<<'\n';csv.flush();
        bool transfer=false;
        if(!resetn){
            if(dut.in_ready || dut.out_valid)fail("CPP_RESET");
            if(!queue.empty()){
                cancelled+=unsigned(queue.size());cover("reset/cancel");
                // With LATENCY=3 this is the cycle where the processing wait is still running.
                if(cycle==queue.front().due-CFG_LATENCY+1)cover("reset/cancel-first-cycle");
            }
            queue.clear();model.reset();held=false;
            // A power-on reset clears nothing, so only a reset after real history is credited.
            if(history_live)after_reset=true;
            history_live=false;
        }else{
            if(held && (!dut.out_valid || data!=held_data))fail("CPP_HOLD");
            const bool due=!queue.empty() && cycle>=queue.front().due;
            if(bool(dut.out_valid)!=due)fail("CPP_LATENCY");
            const bool input_ready=queue.empty() || (due && ready);
            if(bool(dut.in_ready)!=input_ready)fail("CPP_READY");
            if(dut.out_valid){
                const auto& r=queue.front().result;
                const std::int64_t limit=std::int64_t(1)<<(CFG_WIDTH-1);
                if(data!=r.value)fail("CPP_DATA");
                if(ready){
                    cover(data<0?"result/negative":data>0?"result/positive":"result/zero");
                    if(r.sum%4==2)cover("round/tie-positive");
                    if(r.sum%4==-2)cover("round/tie-negative");
                    if(r.clip_high)cover("saturation/high");
                    if(r.clip_low)cover("saturation/low");
                    if(r.clip_high && r.sum<4*limit+2)cover("saturation/high-boundary");
                    if(r.clip_low && r.sum>-4*limit-6)cover("saturation/low-boundary");
                    if(r.history)cover("fir/history");
                    if(after_reset){cover("reset/history-clear");after_reset=false;}
                    cover("timing/latency");queue.pop_front();retired++;
                }else cover("flow/output-stall");
            }
            if(valid && !dut.in_ready)cover("flow/input-stall");
            held=dut.out_valid && !ready;held_data=data;
            if(valid && dut.in_ready){queue.push_back({model.accept(sample),cycle+CFG_LATENCY});accepted++;transfer=true;history_live=history_live||sample!=0;}
            if(queue.size()>1)fail("CPP_OUTSTANDING");
        }
        dut.clk=1;dut.eval();wave.dump(context.time());context.timeInc(5);cycle++;
        return transfer;
    }
    void reset(){resets++;tick(false,false,0,false);tick(false,false,0,false);}
    void cancel_one(){
        while(!tick(true,true,17,false)){}
        while(!dut.out_valid)tick(true,false,0,false);
        for(int i=0;i<3;i++)tick(true,false,0,false);
        reset();
    }
    void cancel_first_cycle(){
        while(!tick(true,true,23,false)){}
        reset();
    }
    void stream(const std::vector<int>& samples,unsigned seed,bool stalls){
        unsigned index=0,guard=0,state=seed?seed:1;bool valid=false;int sample=0;
        auto random=[&](){state^=state<<13;state^=state>>17;state^=state<<5;return state;};
        while(index<samples.size() || valid || !queue.empty()){
            if(!valid && index<samples.size() && (!stalls || random()%3)){valid=true;sample=samples[index];}
            bool ready=!stalls || (cycle%29>=6 && random()%4!=0);
            if(index==samples.size())ready=true;
            if(tick(true,valid,sample,ready)){valid=false;index++;}
            if(++guard>samples.size()*64+256)fail("CPP_TIMEOUT");
        }
        for(int i=0;i<CFG_LATENCY+4;i++)tick(true,false,0,true);
    }
};

int main(int argc,char** argv){
    try{
        if(argc!=8)fail("CPP_INPUT");
        const std::string scenario=argv[1];const unsigned seed=unsigned(std::stoul(argv[2]));
        const unsigned expected=unsigned(std::stoul(argv[3]));const bool faulty=std::string(argv[4])=="1";
        std::ifstream input(argv[5]);std::vector<int> samples;int value;
        if(!input)fail("CPP_INPUT");while(input>>value)samples.push_back(value);
        if(!input.eof() || samples.size()!=expected || !expected)fail("CPP_INPUT");
        Test test(argv[6],argv[7],faulty);test.reset();
        if(scenario=="reset"){test.cancel_one();test.cancel_first_cycle();}
        test.stream(samples,seed,scenario!="basic");
        const unsigned cancel=scenario=="reset"?2:0;
        if(test.accepted!=expected+cancel || test.retired!=expected || test.cancelled!=cancel || !test.queue.empty())fail("CPP_COMPLETION");
        std::cout<<"COUNT accepted="<<test.accepted<<"\nCOUNT retired="<<test.retired<<"\nCOUNT cancelled="<<test.cancelled<<"\nCOUNT resets="<<test.resets<<'\n';
        std::cout<<"RESULT PASS checks="<<test.retired<<'\n';return 0;
    }catch(const std::exception& e){std::cerr<<"CHECK_FAIL "<<e.what()<<'\n';return 1;}
}
