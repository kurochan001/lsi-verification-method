// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#include <systemc>
#include <array>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include "vci_signals.h"
#include "vci_ram.h"
#include "address_decoding_table.cpp"
#undef tmpl
#include "address_masking_table.cpp"
#undef tmpl
#include "linked_access_buffer.cpp"
#undef tmpl
#include "mapping_table.cpp"
#include "segment.cpp"
#include "binary_file_section.cpp"
#include "binary_file_symbol.cpp"
#include "loader.cpp"
#include "caba_base_module.cpp"
#include "vci_target_fsm.cpp"
#undef tmpl
#include "vci_ram.cpp"
#undef tmpl
#ifndef CELL_BYTES
#define CELL_BYTES 4
#endif
using P=soclib::caba::VciParams<CELL_BYTES,8,32,2,1,1,4,2,3,1>;
using Row=std::array<uint64_t,19>;
[[noreturn]] void fail(const char* label){throw std::runtime_error(label);}
void cover(const char* goal){std::cout<<"COVER "<<goal<<'\n';}
struct Sample {bool cmd,rsp;uint64_t data,error,src,trd,pkt,eop;};
struct Test {
 sc_core::sc_signal<bool> clk{"clk"},resetn{"resetn"};soclib::caba::VciSignals<P> bus{"bus"};
 bool cmd_hold=false,rsp_hold=false;std::array<uint64_t,15> old_cmd{};std::array<uint64_t,7> old_rsp{};
 uint64_t rows=0,packets=0,commands=0,responses=0,completed=0,cancelled=0,resets=0,errors=0;
 Sample tick(){
  clk=false;sc_core::sc_start(5,sc_core::SC_NS);
  Sample s{bus.cmdval.read()&&bus.cmdack.read(),bus.rspval.read()&&bus.rspack.read(),bus.rdata.read().to_uint64(),bus.rerror.read().to_uint(),bus.rsrcid.read().to_uint(),bus.rtrdid.read().to_uint(),bus.rpktid.read().to_uint(),bus.reop.read()};
  std::array<uint64_t,15> c={bus.cmdval.read(),bus.cmd.read().to_uint(),bus.address.read().to_uint64(),bus.wdata.read().to_uint64(),bus.be.read().to_uint(),bus.plen.read().to_uint(),bus.eop.read(),bus.srcid.read().to_uint(),bus.trdid.read().to_uint(),bus.pktid.read().to_uint(),bus.contig.read(),bus.wrap.read(),bus.cons.read(),bus.cfixed.read(),bus.clen.read().to_uint()};
  std::array<uint64_t,7> r={bus.rspval.read(),s.data,s.error,s.src,s.trd,s.pkt,s.eop};
  if(resetn.read()){
   if(cmd_hold&&c!=old_cmd)fail("VCI_COMMAND_HOLD");if(rsp_hold&&r!=old_rsp)fail("VCI_RESPONSE_HOLD");
   cmd_hold=bus.cmdval.read()&&!bus.cmdack.read();rsp_hold=bus.rspval.read()&&!bus.rspack.read();
   if(cmd_hold)cover("handshake/command-hold");if(rsp_hold)cover("handshake/response-hold");
   if(s.cmd)commands++;if(s.rsp){responses++;errors+=s.error!=0;}
  }else cmd_hold=rsp_hold=false;
  old_cmd=c;old_rsp=r;clk=true;sc_core::sc_start(5,sc_core::SC_NS);return s;
 }
 void reset(bool count=true){
  resetn=false;bus.cmdval=false;bus.rspack=false;cmd_hold=rsp_hold=false;
  for(int i=0;i<4;i++)tick();resetn=true;
  for(int i=0;i<3;i++){auto s=tick();if(bus.rspval.read()||s.rsp)fail("VCI_STALE_RESPONSE");}
  if(count){resets++;cover("reset/clean-restart");}
 }
 void drive(const Row& r,unsigned beat){
  bus.cmdval=true;bus.cmd=unsigned(r[0]);bus.address=unsigned(r[1]+beat*CELL_BYTES);bus.be=unsigned(r[3]);bus.srcid=unsigned(r[4]);bus.trdid=unsigned(r[5]);bus.pktid=unsigned(r[6]);bus.wdata=P::data_t(r[10+beat]);bus.eop=r[0]==1||beat+1==r[2];bus.plen=unsigned(r[2]*CELL_BYTES);bus.contig=true;bus.wrap=false;bus.cons=false;bus.cfixed=false;bus.clen=0;
 }
 void execute(const Row& r,const Row* next){
  if(!r[0]){reset();rows++;return;}packets++;
  unsigned beats=r[0]==1?1:unsigned(r[2]);
  for(unsigned j=0;j<beats;j++){
   drive(r,j);unsigned cycles=0;
   while(true){auto s=tick();if(s.rsp||bus.rspval.read())fail("VCI_EARLY_RESPONSE");if(s.cmd)break;if(++cycles>2000)fail("VCI_TIMEOUT");}
   if(r[9]==1){cancelled++;cover("reset/command-cancel");reset();rows++;return;}
   bus.cmdval=false;
   if(j+1<beats)for(unsigned g=0;g<r[7];g++){tick();if(bus.rspval.read())fail("VCI_EARLY_RESPONSE");}
  }
  bool ahead=r[0]==1&&!r[9]&&next&&(*next)[0]&&!(*next)[9];
  if(ahead)drive(*next,0);
  unsigned need=r[0]==1?unsigned(r[2]):1;
  for(unsigned i=0;i<need;i++){
   unsigned cycles=0;
   while(!bus.rspval.read()){auto s=tick();if(s.cmd)fail("VCI_EARLY_COMMAND");if(++cycles>2000)fail("VCI_TIMEOUT");}
   for(unsigned k=0;k<r[8];k++){auto s=tick();if(s.cmd)fail("VCI_EARLY_COMMAND");}
   if(r[9]==2){cancelled++;cover("reset/response-cancel");reset();rows++;return;}
   bus.rspack=true;auto s=tick();bus.rspack=false;
   if(!s.rsp)fail("VCI_MISSING_RESPONSE");if(s.cmd)fail("VCI_EARLY_COMMAND");
   if(s.src!=r[4]||s.trd!=r[5]||s.pkt!=r[6])fail("VCI_ID");
   if(s.error!=r[18])fail("VCI_ERROR");if(s.eop!=(i+1==need))fail("VCI_REOP");
   if(r[0]==1&&!r[18]&&s.data!=r[14+i]){std::cerr<<"actual="<<std::hex<<s.data<<" expected="<<r[14+i]<<std::dec<<'\n';fail("VCI_DATA");}
   cover("response/ids");if(s.error)cover("response/unmapped");
  }
  completed++;rows++;cover(r[0]==1?"data/read":"data/write");
  if(r[3]!=(1u<<CELL_BYTES)-1)cover("data/byte-enable");if(r[1]>=0x2000&&r[1]<0x2100)cover("data/second-segment");
  if(r[2]==2)cover("packet/two-cells");if(r[2]==4)cover("packet/four-cells");
 }
};
std::vector<Row> load(const char* path){
 std::ifstream f(path);if(!f)fail("VCI_INPUT");std::vector<Row> out;std::string line;
 while(std::getline(f,line)){
  std::istringstream in(line);Row r{};for(auto& v:r){std::string word;if(!(in>>word)||word.size()>16||word.find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)fail("VCI_INPUT");v=std::stoull(word,nullptr,16);}std::string extra;if(in>>extra)fail("VCI_INPUT");
  uint64_t mask=CELL_BYTES==8?UINT64_MAX:UINT32_MAX;
  if(r[0]>2||r[1]>UINT32_MAX||r[1]%CELL_BYTES||r[2]>4||(r[0]&&r[2]!=1&&r[2]!=2&&r[2]!=4)||r[3]>=(1u<<CELL_BYTES)||(r[0]&&!r[3])||r[4]>=16||r[5]>=8||r[6]>=4||r[7]>4||r[8]>5||r[9]>2||r[18]>1)fail("VCI_INPUT");
  if((r[2]>1||r[0]==1)&&r[3]!=(1u<<CELL_BYTES)-1)fail("VCI_INPUT");if(r[9]==1&&(r[0]!=2||r[2]<2)||r[9]==2&&r[0]!=1)fail("VCI_INPUT");
  for(unsigned j=10;j<18;j++)if(r[j]>mask)fail("VCI_INPUT");out.push_back(r);
  if(!r[0])for(auto v:r)if(v)fail("VCI_INPUT");
 }if(out.empty())fail("VCI_INPUT");return out;
}
int sc_main(int argc,char** argv){
 sc_core::sc_trace_file* trace=nullptr;
 try{
  if(argc!=3)fail("VCI_INPUT");auto rows=load(argv[1]);Test t;
  soclib::common::MappingTable map(32,soclib::common::IntTab(8),soclib::common::IntTab(4),0x00300000);
  map.add(soclib::common::Segment("ram0",0x1000,256,soclib::common::IntTab(0),false));map.add(soclib::common::Segment("ram1",0x2000,256,soclib::common::IntTab(0),false));
  soclib::common::Loader loader;soclib::caba::VciRam<P> ram("ram",soclib::common::IntTab(0),map,loader);ram.p_clk(t.clk);ram.p_resetn(t.resetn);ram.p_vci(t.bus);
  trace=sc_core::sc_create_vcd_trace_file(argv[2]);trace->set_time_unit(1,sc_core::SC_NS);t.bus.trace(trace,"vci");sc_core::sc_trace(trace,t.clk,"clk");sc_core::sc_trace(trace,t.resetn,"resetn");
  t.reset(false);for(size_t i=0;i<rows.size();i++)t.execute(rows[i],i+1<rows.size()?&rows[i+1]:nullptr);
  t.bus.cmdval=false;t.bus.rspack=false;for(int i=0;i<4;i++){auto s=t.tick();if(s.rsp||t.bus.rspval.read())fail("VCI_STALE_RESPONSE");}
  if(t.packets!=t.completed+t.cancelled)fail("VCI_COMPLETION");
  std::cout<<std::dec<<"COUNT rows="<<t.rows<<"\nCOUNT packets="<<t.packets<<"\nCOUNT commands="<<t.commands<<"\nCOUNT responses="<<t.responses<<"\nCOUNT completed="<<t.completed<<"\nCOUNT cancelled="<<t.cancelled<<"\nCOUNT resets="<<t.resets<<"\nCOUNT errors="<<t.errors<<'\n';
  std::cout<<"RESULT PASS checks="<<t.rows<<'\n';sc_core::sc_close_vcd_trace_file(trace);return 0;
 }catch(const std::exception& e){if(trace)sc_core::sc_close_vcd_trace_file(trace);std::cerr<<"CHECK_FAIL "<<e.what()<<'\n';return 1;}
}
