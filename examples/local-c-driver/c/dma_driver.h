#ifndef DMA_DRIVER_H
#define DMA_DRIVER_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { DMA_OK=0, DMA_BUS_ERROR=-1, DMA_TIMEOUT=-2, DMA_ABORTED=-3, DMA_HW_ERROR=-4 };
typedef struct {
 void *user;
 int (*read32)(void *,uint32_t,uint32_t *);
 int (*write32)(void *,uint32_t,uint32_t);
 void (*idle)(void *);
 unsigned fault;
} dma_device;
int dma_submit(dma_device *,uint32_t,uint32_t,uint32_t);
int dma_wait(dma_device *,unsigned);
int dma_abort(dma_device *);
int dma_irq_enable(dma_device *,int);
int dma_ack_irq(dma_device *);
#ifdef __cplusplus
}
#endif
#endif
