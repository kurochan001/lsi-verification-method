#include "Vdma_model.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "dma_driver.h"
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
static VerilatedVcdC* active_trace=nullptr;
[[noreturn]]static void fail(const char*label){std::cout<<"CHECK_FAIL "<<label<<std::endl;if(active_trace)active_trace->flush();std::exit(1);}
struct Fixture{
 VerilatedContext context;Vdma_model dut{&context};VerilatedVcdC trace;
 std::array<uint8_t,8192> memory{};
 uint32_t src=0,dst=0,words=0,seed=0;unsigned period=0,kind=0,cycle=0;
 bool reading=false,writing=false,b_pending=false,frozen=false;
 unsigned ra=0,rlen=0,rb=0,rd=0,wa=0,wlen=0,wb=0,bd=0;uint32_t read_value=0;
 unsigned issued_reads=0,issued_writes=0,written=0,starts=0;
 static uint8_t initial(unsigned s,unsigned a){return uint8_t(s^(a*13)^(a>>5)^(a>>8));}
 uint32_t word(unsigned address){if(address+3>=memory.size())fail("DRIVER_ADDRESS");return uint32_t(memory[address])|(uint32_t(memory[address+1])<<8)|(uint32_t(memory[address+2])<<16)|(uint32_t(memory[address+3])<<24);}
 explicit Fixture(const char*wave){context.traceEverOn(true);dut.trace(&trace,99);trace.open(wave);active_trace=&trace;dut.clk=0;dut.rst_n=0;dut.psel=0;dut.penable=0;dut.pwrite=0;dut.paddr=0;dut.pwdata=0;}
 ~Fixture(){dut.final();trace.close();active_trace=nullptr;}
 void tick(){
  bool permit=period==0 || cycle%(period+1)==period;
  dut.clk=0;dut.arready=!reading&&!frozen&&permit;dut.awready=!writing&&!b_pending&&permit;dut.wready=writing&&permit;
  dut.rvalid=reading&&rd==0;dut.rdata=read_value;dut.rid=1;dut.rresp=kind==2 ? 2:0;dut.rlast=rb==rlen;
  dut.bvalid=b_pending&&bd==0;dut.bid=2;dut.bresp=0;dut.eval();trace.dump(context.time());context.timeInc(5);
  if(!dut.rst_n){reading=writing=b_pending=false;rd=bd=0;}
  else{
   if((dut.arvalid&&!dut.arready)||(dut.wvalid&&!dut.wready))std::cout<<"COVER axi/stall\n";
   if(dut.arvalid&&dut.arready){
    if(dut.araddr!=src+4*issued_reads || dut.arid!=1 || dut.arlen>3 || (dut.araddr%4096)+4*(dut.arlen+1)>4096)fail("DRIVER_ADDRESS");
    ra=dut.araddr;rlen=dut.arlen;rb=0;rd=1;reading=true;issued_reads+=rlen+1;
   }else if(reading){
    if(rd){read_value=word(ra+4*rb);--rd;}
    else if(dut.rvalid&&dut.rready){if(rb==rlen)reading=false;else{++rb;rd=1;}}
   }
   if(dut.awvalid&&dut.awready){
    if(dut.awaddr!=dst+4*issued_writes || dut.awid!=2 || dut.awlen>3 || (dut.awaddr%4096)+4*(dut.awlen+1)>4096)fail("DRIVER_ADDRESS");
    wa=dut.awaddr;wlen=dut.awlen;wb=0;writing=true;issued_writes+=wlen+1;
   }else if(dut.wvalid&&dut.wready){
    uint32_t expected=0;for(unsigned lane=0;lane<4;lane++)expected|=uint32_t(initial(seed,src+4*written+lane))<<(8*lane);
    if(dut.wdata!=expected || dut.wstrb!=15 || bool(dut.wlast)!=(wb==wlen))fail("DRIVER_DATA");
    for(unsigned lane=0;lane<4;lane++)memory[wa+4*wb+lane]=uint8_t(dut.wdata>>(8*lane));
    ++written;if(wb==wlen){writing=false;b_pending=true;bd=1;}else ++wb;
   }else if(b_pending){if(bd)--bd;else if(dut.bvalid&&dut.bready)b_pending=false;}
  }
  dut.clk=1;dut.eval();trace.dump(context.time());context.timeInc(5);dut.clk=0;dut.eval();++cycle;
  if(cycle>3000000)fail("DRIVER_TIMEOUT");
 }
 void reset(){dut.rst_n=0;dut.psel=0;dut.penable=0;frozen=false;for(int i=0;i<3;i++)tick();dut.rst_n=1;tick();}
 void setup(unsigned source,unsigned destination,unsigned length,unsigned value){src=source;dst=destination;words=length;seed=value;issued_reads=issued_writes=written=0;}
 static int read(void*ptr,uint32_t address,uint32_t*value){return static_cast<Fixture*>(ptr)->access(address,0,false,value);}
 static int write(void*ptr,uint32_t address,uint32_t value){return static_cast<Fixture*>(ptr)->access(address,value,true,nullptr);}
 static void idle(void*ptr){static_cast<Fixture*>(ptr)->tick();}
 int access(uint32_t address,uint32_t data,bool write,uint32_t*value){
  if(write&&address==8&&data!=words)fail("DRIVER_CONFIG");
  dut.psel=1;dut.penable=0;dut.pwrite=write;dut.paddr=address;dut.pwdata=data;tick();
  dut.penable=1;dut.eval();if(!dut.pready)fail("DRIVER_APB");int error=dut.pslverr;
  if(value)*value=dut.prdata;
  if(write&&!error&&address==12&&(data&1))++starts;
  tick();dut.psel=0;dut.penable=0;dut.eval();return error;
 }
 void check_memory(unsigned copied){
  if(written!=copied || issued_writes!=copied)fail("DRIVER_COMPLETION");
  for(unsigned a=0;a<memory.size();a++){
   uint8_t expected=initial(seed,(a>=dst&&a<dst+4*copied) ? src+a-dst:a);
   if(memory[a]!=expected)fail("DRIVER_MEMORY");
  }
 }
};
int main(int argc,char**argv){
 if(argc!=4)return 2;std::ifstream input(argv[1]);if(!input)return 2;
 Fixture f(argv[2]);dma_device d{&f,Fixture::read,Fixture::write,Fixture::idle,unsigned(std::stoul(argv[3]))};
 unsigned type,source,destination,length,seed,period,checks=0,copies=0,errors=0,timeouts=0;
 while(input>>std::hex>>type>>source>>destination>>length>>seed>>period){
  f.reset();f.kind=type;f.period=period;f.setup(source,destination,length,seed);
  for(unsigned a=0;a<f.memory.size();a++)f.memory[a]=Fixture::initial(seed,a);
  if(dma_irq_enable(&d,type!=4)!=DMA_OK)fail("DRIVER_IRQ");f.frozen=type==3;
  if(dma_submit(&d,source,destination,length)!=DMA_OK)fail("DRIVER_CONFIG");std::cout<<"COVER apb/program\n";
  int result=dma_wait(&d,type==3 ? 4:1000);
  if(type==3){
   if(result!=DMA_TIMEOUT)fail("DRIVER_COMPLETION");++timeouts;std::cout<<"COVER driver/timeout\n";
   if(dma_abort(&d)!=DMA_OK)fail("DRIVER_CONFIG");f.frozen=false;
   if(dma_wait(&d,1000)!=DMA_ABORTED)fail("DRIVER_STATUS");f.check_memory(0);
   if(dma_ack_irq(&d)!=1)fail("DRIVER_IRQ");uint32_t status=0;Fixture::read(&f,16,&status);if(status&16)fail("DRIVER_IRQ");
   f.kind=0;f.setup(0,512,2,seed);
   if(dma_submit(&d,0,512,2)!=DMA_OK || dma_wait(&d,1000)!=DMA_OK)fail("DRIVER_COMPLETION");f.check_memory(2);++copies;std::cout<<"COVER driver/abort-recovery\n";
  }else if(type==1 || type==2){
   if(result!=DMA_HW_ERROR)fail("DRIVER_STATUS");f.check_memory(0);++errors;std::cout<<"COVER transfer/error\n";
  }else{
   if(result!=DMA_OK)fail("DRIVER_COMPLETION");uint32_t status=0;Fixture::read(&f,16,&status);
   if((status&15)!=2)fail("DRIVER_COMPLETION");f.check_memory(length);++copies;std::cout<<"COVER transfer/copy\n";
  }
  uint32_t status=0;Fixture::read(&f,16,&status);if(!(status&16))fail("DRIVER_IRQ");
  if(type==4){if(f.dut.irq)fail("DRIVER_IRQ");if(dma_irq_enable(&d,1)!=DMA_OK || !f.dut.irq)fail("DRIVER_IRQ");std::cout<<"COVER irq/mask\n";}
  if(dma_ack_irq(&d)!=1)fail("DRIVER_IRQ");Fixture::read(&f,16,&status);if((status&16)||f.dut.irq)fail("DRIVER_IRQ");std::cout<<"COVER irq/ack\n";
  ++checks;
 }
 if(!input.eof())return 2;
 std::cout<<"COUNT starts="<<std::dec<<f.starts<<"\nCOUNT copies="<<copies<<"\nCOUNT errors="<<errors<<"\nCOUNT timeouts="<<timeouts<<"\nRESULT PASS checks="<<checks<<std::endl;
 return 0;
}
