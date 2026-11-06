// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#include "Vdut.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "model.hpp"
#include <ngspice/sharedspice.h>
#include <dlfcn.h>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

constexpr double CLOCK_SECONDS=1e-5;
constexpr double VOLTAGE_TOLERANCE=2e-4;
[[noreturn]] void fail(const char* label){throw std::runtime_error(label);}
void cover(const char* goal){std::cout<<"COVER "<<goal<<'\n';}
struct Row {unsigned resetn,enable,low,high,millivolts;};
struct Edge {double seconds,voltage;};

class Spice {
    void* handle_;
    template<class F>F symbol(const char* name){auto p=dlsym(handle_,name);if(!p)fail("SPICE_API");return reinterpret_cast<F>(p);}
public:
    decltype(&ngSpice_Init) init;
    decltype(&ngSpice_Init_Sync) sync;
    decltype(&ngSpice_Circ) circuit;
    decltype(&ngSpice_Command) command;
    decltype(&ngSpice_SetBkpt) breakpoint;
    explicit Spice(const char* path):handle_(dlopen(path,RTLD_NOW|RTLD_LOCAL)){
        if(!handle_)fail("SPICE_API");
        init=symbol<decltype(init)>("ngSpice_Init");sync=symbol<decltype(sync)>("ngSpice_Init_Sync");
        circuit=symbol<decltype(circuit)>("ngSpice_Circ");command=symbol<decltype(command)>("ngSpice_Command");
        breakpoint=symbol<decltype(breakpoint)>("ngSpice_SetBkpt");
        symbol<int(*)()>("ngSpice_nospinit")();symbol<int(*)()>("ngSpice_nospiceinit")();
    }
    // One library instance per process; all simulator callbacks live until exit.
    void cmd(std::string value){if(command(value.data()))fail("SPICE_ENGINE");}
};

struct Test {
    Spice& api;
    const std::vector<Row> rows;
    double resistance,capacitance;
    int fault;
    const std::string deck_path;
    VerilatedContext context;
    Vdut dut{&context};
    VerilatedVcdC wave;
    std::ofstream csv;
    std::vector<Edge> drive_history{{0,0}};
    std::string error;
    bool version=false,model_drive=false,previous_reset=false;
    double reference=0,last_time=0,expected_source=0,max_error=0;
    unsigned samples=0,points=0,source_queries=0,resets=0,disabled=0;
    Test(Spice& spice,std::vector<Row> program,double r,double c,int injection,const char* circuit_path,const char* vcd,const char* trace):
        api(spice),rows(std::move(program)),resistance(r),capacitance(c),fault(injection),deck_path(circuit_path),csv(trace){
        if(!csv)fail("SPICE_TRACE");
        context.traceEverOn(true);dut.trace(&wave,99);wave.open(vcd);
        dut.clk=0;dut.rst_n=0;dut.enable=0;dut.adc=0;dut.low_code=0;dut.high_code=1;dut.eval();wave.dump(0);
        context.time(1);dut.clk=1;dut.eval();wave.dump(1);
        csv<<"time_s,spice_voltage,analytic_voltage,dac_voltage,clock_edge,adc,drive,reset_n,enable\n"<<std::setprecision(17);
    }
    ~Test(){dut.final();wave.close();}
    void set_error(const char* value){if(error.empty())error=value;}
    double source(double time)const{
        double value=0;
        // Left-continuous boundary values: a newly sampled control affects t>T.
        for(const auto& edge:drive_history){if(edge.seconds<time)value=edge.voltage;else break;}
        return fault==3?0:value;
    }
    void sample(pvecvaluesall data){
        if(!error.empty())return;
        double time=-1,voltage=0,dac=0;bool have_voltage=false,have_dac=false;
        for(int i=0;i<data->veccount;i++){
            auto v=data->vecsa[i];if(v->is_complex)fail("SPICE_TRACE");
            std::string name=v->name;
            if(name=="time")time=v->creal;
            else if(name=="filtered"){voltage=v->creal;have_voltage=true;}
            else if(name=="dac"){dac=v->creal;have_dac=true;}
        }
        if(!have_voltage || !have_dac || !std::isfinite(time) || time<0 || !std::isfinite(voltage) || !std::isfinite(dac) || unsigned(data->vecindex)!=points || (points && time<=last_time))fail("SPICE_TRACE");
        reference=rc_advance(reference,expected_source,time-last_time,resistance,capacitance);last_time=time;points++;
        const double difference=std::abs(voltage-reference);max_error=std::max(max_error,difference);
        unsigned adc=reference_adc(voltage,CFG_ADC_BITS);
        csv<<time<<','<<voltage<<','<<reference<<','<<dac<<",0,"<<adc<<','<<unsigned(dut.drive)<<','<<unsigned(dut.rst_n)<<','<<unsigned(dut.enable)<<'\n';csv.flush();
        double desired_dac=0;for(const auto& edge:drive_history){if(edge.seconds<time)desired_dac=edge.voltage;else break;}
        if(std::abs(dac-desired_dac)>VOLTAGE_TOLERANCE)fail("SPICE_DAC");
        if(difference>VOLTAGE_TOLERANCE)fail("SPICE_ANALOG");
        if(voltage < -VOLTAGE_TOLERANCE || voltage>3.6+VOLTAGE_TOLERANCE)fail("SPICE_RANGE");
        cover("analog/rc-match");cover("analog/range");
        if(expected_source>voltage+1e-3)cover("analog/charge");
        if(expected_source<voltage-1e-3)cover("analog/discharge");
        const double target=(samples+1)*CLOCK_SECONDS;
        if(time>target+1e-12)fail("SPICE_TIME");
        if(samples<rows.size() && std::abs(time-target)<=1e-12){
            const auto& row=rows[samples];
            const bool old=model_drive;
            const bool wanted=next_drive(old,row.resetn,row.enable,adc,row.low,row.high);
            // Adapter conversion and independent lround specification are separate.
            const unsigned delivered=fault==2?0:unsigned(std::floor(std::clamp(voltage,0.0,3.3)*double((1u<<CFG_ADC_BITS)-1)/3.3+0.5));
            const std::uint64_t ps=std::uint64_t(std::llround(target*1e12));
            context.time(ps-1);dut.clk=0;dut.rst_n=row.resetn;dut.enable=row.enable;dut.adc=delivered;dut.low_code=row.low;dut.high_code=row.high;dut.eval();wave.dump(context.time());
            context.time(ps);dut.clk=1;dut.eval();wave.dump(context.time());
            csv<<time<<','<<voltage<<','<<reference<<','<<dac<<",1,"<<delivered<<','<<unsigned(dut.drive)<<','<<row.resetn<<','<<row.enable<<'\n';csv.flush();
            if(delivered!=adc)fail("SPICE_ADC");
            if(bool(dut.drive)!=wanted)fail("SPICE_CONTROL");
            if(!row.resetn){resets++;cover("reset/digital-clear");if(voltage>0.05)cover("reset/plant-memory");}
            if(!row.enable){disabled++;cover("input/enable-off");}
            if(row.resetn && !previous_reset && samples>2)cover("reset/restart");  // row 1 is the startup reset, not a restart
            cover(wanted?"control/drive-on":"control/drive-off");
            if(row.resetn && row.enable && adc>row.low && adc<row.high)cover(old?"control/hold-on":"control/hold-off");
            if(samples && (row.low!=rows[samples-1].low || row.high!=rows[samples-1].high))cover("input/setpoint-step");
            if(samples && row.millivolts!=rows[samples-1].millivolts)cover("input/supply-step");
            cover("time/clock-boundary");
            previous_reset=row.resetn;model_drive=wanted;
            expected_source=wanted?row.millivolts/1000.0:0;
            drive_history.push_back({target,dut.drive?row.millivolts/1000.0:0});samples++;
        }
    }
    static int text(char* line,int,void* p){
        auto& t=*static_cast<Test*>(p);std::string s=line;
        if(s.find("ngspice-47")!=std::string::npos)t.version=true;
        if(s.find("Error:")!=std::string::npos || s.find("LSI_UNEXPECTED_USER_INIT")!=std::string::npos)t.set_error("SPICE_ENGINE");
        std::cout<<s<<'\n';return 0;
    }
    static int exited(int,bool,bool,int,void* p){static_cast<Test*>(p)->set_error("SPICE_ENGINE");return 0;}
    static int initialize(pvecinfoall,int,void*){return 0;}
    static int send(pvecvaluesall data,int,int,void* p){
        auto& t=*static_cast<Test*>(p);
        try{t.sample(data);}catch(const std::exception& e){t.set_error(e.what());}catch(...){t.set_error("SPICE_CALLBACK");}
        return 0;
    }
    static int voltage(double* value,double time,char* name,int,void* p){
        auto& t=*static_cast<Test*>(p);t.source_queries++;
        try{
            std::string n=name;for(char& c:n)c=char(std::tolower(static_cast<unsigned char>(c)));
            if(n!="vdrive")fail("SPICE_API");*value=t.source(time);
        }catch(...){*value=0;t.set_error("SPICE_API");}
        return 0;
    }
    void run(){
        if(api.init(text,nullptr,exited,send,initialize,nullptr,this))fail("SPICE_ENGINE");
        int id=0;if(api.sync(voltage,nullptr,nullptr,&id,this))fail("SPICE_ENGINE");
        api.cmd("version");if(!version)fail("SPICE_VERSION");
        std::ifstream input(deck_path);std::vector<std::string> deck;std::string line;
        if(!input)fail("SPICE_INPUT");while(std::getline(input,line))deck.push_back(line);
        if(deck.empty())fail("SPICE_INPUT");
        std::vector<char*> pointers;for(auto& line:deck)pointers.push_back(line.data());pointers.push_back(nullptr);
        if(api.circuit(pointers.data()))fail("SPICE_ENGINE");
        for(unsigned k=1;k<=rows.size();k++)if(!api.breakpoint(k*CLOCK_SECONDS))fail("SPICE_TIME");
        std::ostringstream command;command<<std::setprecision(17)<<"tran "<<CLOCK_SECONDS/20<<' '<<rows.size()*CLOCK_SECONDS<<" 0 "<<CLOCK_SECONDS/20<<" uic";
        api.cmd(command.str());
        if(!error.empty())fail(error.c_str());
        if(samples!=rows.size() || points<2*samples || source_queries<points || std::abs(last_time-rows.size()*CLOCK_SECONDS)>1e-12)fail("SPICE_COMPLETION");
        std::ofstream metrics("metrics.json");metrics<<std::setprecision(17)<<"{\"analog_points\":"<<points<<",\"source_queries\":"<<source_queries<<",\"samples\":"<<samples<<",\"last_time\":"<<last_time<<",\"max_error\":"<<max_error<<"}\n";
        std::cout<<"COUNT samples="<<samples<<"\nCOUNT resets="<<resets<<"\nCOUNT disabled="<<disabled<<"\nCOUNT updates="<<drive_history.size()-1<<'\n';
        std::cout<<"RESULT PASS checks="<<samples<<'\n';
    }
};

int main(int argc,char** argv){
    try{
        if(argc!=10)fail("SPICE_INPUT");
        std::ifstream file(argv[2]);std::vector<Row> rows;Row row;
        if(!file)fail("SPICE_INPUT");
        std::string line;
        while(std::getline(file,line)){
            std::istringstream fields(line);std::string extra;
            if(!(fields>>row.resetn>>row.enable>>row.low>>row.high>>row.millivolts) || fields>>extra)fail("SPICE_INPUT");
            if(row.resetn>1 || row.enable>1 || row.low>=row.high || row.high>=(1u<<CFG_ADC_BITS) || row.millivolts<2000 || row.millivolts>3600)fail("SPICE_INPUT");rows.push_back(row);
        }
        const double r=std::stod(argv[4]),c=std::stod(argv[5]);const int fault=std::stoi(argv[6]);
        if(!file.eof() || rows.empty() || rows.size()>2000 || !std::isfinite(r) || !std::isfinite(c) || r<=0 || c<=0 || fault<0 || fault>3)fail("SPICE_INPUT");
        Spice api(argv[3]);Test test(api,std::move(rows),r,c,fault,argv[7],argv[8],argv[9]);test.run();return 0;
    }catch(const std::exception& e){std::cerr<<"CHECK_FAIL "<<e.what()<<'\n';return 1;}
}
