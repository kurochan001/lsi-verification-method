#include "demo_regs.h"
#include <stdio.h>
#ifdef BAD_HEADER
#undef DEMO_CFG_ADDR
#define DEMO_CFG_ADDR 4u
#endif
int main(void){
 if(DEMO_CFG_ADDR!=0 || DEMO_CFG_MASK!=255 || DEMO_CFG_RESET!=18 || DEMO_IDREG_ADDR!=4 || DEMO_IDREG_MASK!=0xffffffffu || DEMO_IDREG_RESET!=0x52444c31 || DEMO_PENDING_ADDR!=8 || DEMO_PENDING_MASK!=15 || DEMO_PENDING_RESET!=0){puts("CHECK_FAIL RDL_HEADER");return 1;}
 puts("COUNT views=1\nRESULT PASS checks=1");return 0;
}
