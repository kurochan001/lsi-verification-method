#include "dma_driver.h"
int dma_submit(dma_device *d,uint32_t src,uint32_t dst,uint32_t words){
 if(d->write32(d->user,0,src) || d->write32(d->user,4,dst) ||
    d->write32(d->user,8,d->fault==1 ? words*4:words) || d->write32(d->user,12,1))return DMA_BUS_ERROR;
 return DMA_OK;
}
int dma_wait(dma_device *d,unsigned limit){
 for(unsigned i=0;i<limit;i++){
  uint32_t status;
  if(d->read32(d->user,16,&status))return DMA_BUS_ERROR;
  if(d->fault==2 && (status&1))return DMA_OK;
  if(status&2){
   if(status&8)return DMA_ABORTED;
   if((status&4) && d->fault!=4)return DMA_HW_ERROR;
   return DMA_OK;
  }
  d->idle(d->user);
 }
 return DMA_TIMEOUT;
}
int dma_abort(dma_device *d){return d->write32(d->user,12,2) ? DMA_BUS_ERROR:DMA_OK;}
int dma_irq_enable(dma_device *d,int enabled){return d->write32(d->user,20,enabled!=0) ? DMA_BUS_ERROR:DMA_OK;}
int dma_ack_irq(dma_device *d){
 uint32_t status;
 if(d->read32(d->user,16,&status))return DMA_BUS_ERROR;
 if(!(status&16))return 0;
 if(d->write32(d->user,d->fault==3 ? 20:12,d->fault==3 ? 0:4))return DMA_BUS_ERROR;
 return 1;
}
