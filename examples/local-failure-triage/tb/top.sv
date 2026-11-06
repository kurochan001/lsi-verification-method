`timescale 1ns/1ps
module top;
  bit clk=0,rst_n=0,event_accept=0,clear_accept=0,irq_en=0,launch=0;
  wire [3:0] pending_values,irq_values;
  int mutation,model,sva_off,sva_mode,hang,planned,checks,compared,fd,fields,r,e,c,en;
  bit expected;
  wire pend=pending_values[mutation],irq=irq_values[mutation];
  for(genvar m=0;m<4;m++)begin: variants
    irq_pending #(.MUTATION(m)) dut(clk,rst_n,event_accept,clear_accept,irq_en,pending_values[m],irq_values[m]);
  end
  always #5 clk=!clk;
  ap_event:assert property(@(posedge clk) disable iff(!rst_n || sva_off!=0 || sva_mode!=0)
    (launch && event_accept)|=>pend)
    else begin $display("CHECK_FAIL SVA_EVENT");$fatal(1,"event must remain pending");end
  // Deliberately wrong proposal: the consequent reads the value BEFORE the event.
  ap_bad_past:assert property(@(posedge clk) disable iff(!rst_n || sva_off!=0 || sva_mode!=1)
    (launch && event_accept)|=>$past(pend))
    else begin $display("CHECK_FAIL SVA_PAST");$fatal(1,"proposal used an old value");end
  ap_vacuous:assert property(@(posedge clk) disable iff(!rst_n || sva_off!=0 || sva_mode!=2)
    (launch && event_accept && !event_accept)|=>pend)
    else begin $display("CHECK_FAIL SVA_VACUOUS");$fatal(1,"unreachable antecedent");end
  cp_event:cover property(@(posedge clk) sva_off==0 && launch && rst_n && event_accept)$display("REVIEW_COVER cp_event");
  cp_collision:cover property(@(posedge clk) sva_off==0 && launch && rst_n && event_accept && clear_accept)$display("REVIEW_COVER cp_collision");
  cp_masked:cover property(@(posedge clk) sva_off==0 && launch && rst_n && event_accept && !irq_en)$display("REVIEW_COVER cp_masked");
  cp_reset_pending:cover property(@(posedge clk) sva_off==0 && launch && !rst_n && pend)$display("REVIEW_COVER cp_reset_pending");
  cp_obligation:cover property(@(posedge clk) sva_off==0 && launch && rst_n && event_accept &&
    (sva_mode!=2 || !event_accept))$display("REVIEW_COVER cp_obligation");
  initial begin
    string vectors,wave;
    if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave) || !$value$plusargs("CHECKS=%d",planned))$fatal(1,"missing arguments");
    void'($value$plusargs("MUTATION=%d",mutation));void'($value$plusargs("MODEL=%d",model));
    void'($value$plusargs("SVA_OFF=%d",sva_off));void'($value$plusargs("SVA_MODE=%d",sva_mode));void'($value$plusargs("HANG=%d",hang));
    if(mutation<0 || mutation>3 || model<0 || model>2 || sva_mode<0 || sva_mode>2)$fatal(1,"invalid mode");
    $dumpfile(wave);$dumpvars(0,top);
    $display("REVIEW_CONFIG mutation=%0d model=%0d sva_off=%0d sva_mode=%0d",mutation,model,sva_off,sva_mode);
    if(hang!=0)forever @(posedge clk);
    fd=$fopen(vectors,"r");if(fd==0)$fatal(1,"cannot open vectors");
    while(!$feof(fd))begin
      fields=$fscanf(fd,"%d %d %d %d\n",r,e,c,en);if(fields!=4)$fatal(1,"bad vector format");
      @(negedge clk);rst_n=r!=0;event_accept=e!=0;clear_accept=c!=0;irq_en=en!=0;launch=checks<planned-1;
      @(posedge clk);#1;
      if(!rst_n)expected=0;
      else if(model==1 && clear_accept)expected=0;
      else if(event_accept)expected=1;
      else if(clear_accept)expected=0;
      $display("TRACE cycle=%0d rst=%0d event=%0d clear=%0d enable=%0d pend=%0d irq=%0d expected=%0d",checks,rst_n,event_accept,clear_accept,irq_en,pend,irq,expected);
      checks++;
      if(model!=2)begin
        compared++;
        if(pend!==expected || irq!==(expected && irq_en))begin
          $display("CHECK_FAIL TRIAGE_COMPARE");$fatal(1,"pending/reference mismatch");
        end
      end
    end
    $fclose(fd);
    if(checks!=planned || launch || !rst_n || event_accept || clear_accept)$fatal(1,"missing final observation cycle");
    $display("TRIAGE_COMPARED compared=%0d",compared);
    $display("RESULT PASS checks=%0d",checks);$finish;
  end
endmodule
