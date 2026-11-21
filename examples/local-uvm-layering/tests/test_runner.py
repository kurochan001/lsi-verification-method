import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
S=importlib.util.spec_from_file_location('layering_runner',Path(__file__).resolve().parents[1]/'run.py');M=importlib.util.module_from_spec(S);S.loader.exec_module(M)


class Log:
    """Builds the log a simulation would print, from a hand-written schedule and the cycle model."""
    def __init__(self):
        self.port=M.Port();self.lines=[];self.cycles=0;self.transfers=0;self.frames=0;self.alarms=0;self.reads=[]
        self.cycle(rst=0);self.cycle()
        self.transfer(M.SETUP,1,M.ENABLE,7)
    def cycle(self,req=0,write=0,addr=0,wdata=0,alarm=0,rst=1):
        self.cycles+=1;self.alarms+=alarm
        self.lines.append('LAYER_SAMPLE '+' '.join(map(str,[self.cycles,rst,req,write,addr,wdata,alarm,*self.port.outputs()])))
        self.port.edge(rst,req,write,addr,wdata,alarm)
    def transfer(self,src,write,addr,wdata=0,alarm=0):
        self.cycle(1,write,addr,wdata,alarm);self.transfers+=1
        self.lines.append(f'LAYER_XFER {self.transfers} {src} {write} {addr} {wdata} {self.port.rdata}')
        value=self.port.rdata;self.cycle();return value
    def frame(self,data):
        self.transfer(M.FRAME,1,M.CTRL,1)
        for byte in data:self.transfer(M.FRAME,1,M.DATA,byte)
        self.transfer(M.FRAME,1,M.CTRL,2);self.frames+=1
    def pair(self,src,index,gap=0):
        self.transfer(src,1,M.INDEX,index)
        for _ in range(gap):self.cycle()
        return self.transfer(src,0,M.VALUE)
    def service(self,alarm_at_clear=0):
        status=self.transfer(M.ISR,0,M.STATUS);self.reads.append(status)
        if status&1:self.pair(M.ISR,0);self.pair(M.ISR,1)
        if status&2:self.pair(M.ISR,3)
        self.transfer(M.ISR,1,M.STATUS,status,alarm_at_clear)
    def step(self,number,kind,edge):self.lines.append(f'LAYER_STEP {number} {kind} {edge}')
    def text(self,steps):
        counts=dict(steps=steps,transfers=self.transfers,frames=self.frames,alarms=self.alarms,
                    served_done=sum(r&1 for r in self.reads),served_alarm=sum(r>>1&1 for r in self.reads),services=len(self.reads))
        return '\n'.join(self.lines)+'\nLAYER_COMPLETE '+' '.join(f'{k}={v}' for k,v in counts.items())+'\n'


def small_plan():
    packets={1:[dict(port=1,seq=0,payload=[1,2],gap=0)],0:[dict(port=0,seq=0,payload=[9],gap=0),dict(port=0,seq=1,payload=[7],gap=0)]}
    return dict(packets=packets,steps=[[M.BACKLOG,1,1,0,0,0,0,0,0],[M.CONTEND]+[0]*8,[M.W1C_LATE]+[0]*8,[M.W1C_SAME]+[0]*8])


def good_log(order=('urgent','bulk'),separate=False,grab=True,keep_late=True):
    log=Log();frames=dict(urgent=[0x80,1,2],bulk=[0x00,9])
    log.step(0,M.BACKLOG,'begin')
    for name in order:log.frame(frames[name]);log.service()
    log.step(0,M.BACKLOG,'end');log.step(1,M.CONTEND,'begin')
    log.transfer(M.HOLD,1,M.INDEX,2,alarm=1)
    if separate:log.transfer(M.LATE,1,M.INDEX,3)
    log.transfer(M.HOLD,0,M.VALUE);log.pair(M.HOLD,3)
    if grab:log.service();log.pair(M.LATE,3);log.pair(M.LATE,2)
    else:log.pair(M.LATE,3);log.pair(M.LATE,2);log.service()
    log.step(1,M.CONTEND,'end');log.step(2,M.W1C_LATE,'begin')
    log.frame([0x01,7])
    status=log.transfer(M.ISR,0,M.STATUS);log.reads.append(status)
    log.transfer(M.ISR,1,M.INDEX,0,alarm=1);log.transfer(M.ISR,0,M.VALUE);log.pair(M.ISR,1)
    log.transfer(M.ISR,1,M.STATUS,status if keep_late else 7)
    if keep_late:log.service()
    log.step(2,M.W1C_LATE,'end');log.step(3,M.W1C_SAME,'begin')
    log.cycle(alarm=1);log.cycle();log.service(alarm_at_clear=1);log.service()
    log.step(3,M.W1C_SAME,'end')
    return log.text(4)


class LayeringTests(unittest.TestCase):
    def test_plan_is_reproducible_and_uses_every_packet_once(self):
        for seed in (0,17,73):
            p=M.plan(seed,3);self.assertEqual(p,M.plan(seed,3));self.assertNotEqual(p,M.plan(seed+1,3))
            frames=M.expected_frames(p);self.assertEqual(sum(len(u)+len(b) for _,u,b in frames),len(p['packets'][0])+len(p['packets'][1]))
            self.assertEqual([row[0] for row in p['steps']][:5],[M.BACKLOG,M.HAZARD,M.CONTEND,M.W1C_LATE,M.W1C_SAME])
            rows=[line.split() for line in M.plan_text(p).splitlines()];self.assertTrue(all(len(row)==9 for row in rows))
            self.assertEqual(sum(row[0]!='0' for row in rows),len(p['steps']))
    def test_unused_or_missing_packets_in_a_plan_are_rejected(self):
        p=M.plan(17,1);extra=copy.deepcopy(p);extra['packets'][0].append(dict(port=0,seq=9,payload=[1],gap=0))
        with self.assertRaises(ValueError):M.expected_frames(extra)
        short=copy.deepcopy(p);short['packets'][1].pop()
        with self.assertRaises(IndexError):M.expected_frames(short)
    def test_model_assembles_a_frame_and_reports_it_one_clock_later(self):
        port=M.Port();port.edge(0,0,0,0,0,0)
        for write,addr,data in ((1,M.ENABLE,7),(1,M.CTRL,1),(1,M.DATA,0x81),(1,M.DATA,5),(1,M.CTRL,2)):port.edge(1,1,write,addr,data,0)
        self.assertEqual(port.outputs(),[1,0,1,1,0x81,2,0x86]);self.assertEqual(port.table,[2,0x86,1,0])
        port.edge(1,0,0,0,0,0);self.assertEqual(port.outputs()[3],0)
    def test_model_counts_protocol_errors_and_restarts_the_frame(self):
        port=M.Port();port.edge(0,0,0,0,0,0)
        for addr,data in ((M.DATA,1),(M.CTRL,2),(M.CTRL,1),(M.DATA,4),(M.CTRL,1),(M.DATA,6),(M.CTRL,2)):port.edge(1,1,1,addr,data,0)
        self.assertEqual(port.table,[1,6,1,3]);self.assertEqual(port.status,5)
    def test_model_keeps_a_cause_that_arrives_with_its_clear(self):
        port=M.Port();port.edge(0,0,0,0,0,0);port.edge(1,0,0,0,0,1);self.assertEqual(port.status,2)
        port.edge(1,1,1,M.STATUS,2,1);self.assertEqual(port.status,2)
        port.edge(1,1,1,M.STATUS,1,0);self.assertEqual(port.status,2)
        port.edge(1,1,1,M.STATUS,2,0);self.assertEqual(port.status,0)
    def test_read_returns_the_value_before_the_clock(self):
        port=M.Port();port.edge(0,0,0,0,0,0);port.edge(1,1,1,M.INDEX,2,0);port.edge(1,1,0,M.INDEX,0,1)
        self.assertEqual(port.outputs()[:2],[1,2]);port.edge(1,1,0,M.STATUS,0,0);self.assertEqual(port.rdata,2)
    def test_hand_written_log_is_accepted_with_the_goals_it_contains(self):
        counts,goals=M.analyse(good_log(),small_plan())
        self.assertEqual((counts['frames'],counts['alarms'],counts['services']),(3,4,7))
        self.assertEqual(set(goals),{'cycle_model','both_ports','backlog_priority','grab_overtakes_lock','lock_delays_isr','alarm_serviced','done_serviced','w1c_late','w1c_same'})
    def test_low_priority_first_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'high-priority'):M.analyse(good_log(order=('bulk','urgent')),small_plan())
    def test_separated_pair_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'separated'):M.analyse(good_log(separate=True),small_plan())
    def test_service_behind_a_queued_lock_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'too many transfers'):M.analyse(good_log(grab=False),small_plan())
    def test_lost_second_cause_is_rejected(self):
        with self.assertRaises(ValueError):M.analyse(good_log(keep_late=False),small_plan())
    def test_changed_output_missing_step_and_wrong_counts_are_rejected(self):
        good=good_log();lines=good.splitlines()
        index=next(i for i,line in enumerate(lines) if line.startswith('LAYER_SAMPLE') and line.split()[11]=='1')
        words=lines[index].split();words[14]=str(int(words[14])^1);changed='\n'.join(lines[:index]+[' '.join(words)]+lines[index+1:])+'\n'
        for text,message in ((changed,'cycle model'),(good.replace('LAYER_STEP 3 5 end\n',''),'steps did not complete'),
                             (good.replace('frames=3','frames=4'),'completion'),(good+good.splitlines()[-1]+'\n','completion'),
                             (good.replace('LAYER_SAMPLE 3 ','LAYER_SAMPLE 4 ',1),'numbering'),(good.replace('LAYER_SAMPLE 3 1 ','LAYER_SAMPLE 3 x ',1),'malformed'),
                             (good.replace('LAYER_XFER 2 0 ','LAYER_XFER 2 1 ',1),'frame'),(good.replace('LAYER_XFER 3 0 1 1 128','LAYER_XFER 3 0 1 1 129',1),'driver log')):
            with self.assertRaisesRegex(ValueError,message):M.analyse(text,small_plan())
    def test_packets_of_another_step_or_order_are_rejected(self):
        p=small_plan();p['packets'][0][0]['payload']=[8]
        with self.assertRaisesRegex(ValueError,'delivered other packets'):M.analyse(good_log(),p)
    def test_unexpected_uvm_errors_warnings_and_versions_are_rejected(self):
        good='Accellera:1800.2:UVM:2020.3.2\nUVM_WARNING x [NO_DPI_USED] expected\nUVM_WARNING x [NO_VISIT_CHECK] expected\nUVM_ERROR : 0\nUVM_FATAL : 0\nUVM_WARNING : 2\n'
        M.normal_report(good)
        for bad in (good.replace('UVM_ERROR : 0','UVM_ERROR : 1'),good.replace('NO_VISIT_CHECK','SEQREQZMB'),good.replace('2020.3.2','2020.3.1')):
            with self.assertRaises(ValueError):M.normal_report(bad)
    def test_requirements_list_every_goal_once(self):
        self.assertEqual(len(M.requirements()['requirements']),6);original=M.REQUIREMENTS
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data=json.loads(original.read_text());data['requirements'][0]['goals'].pop();M.REQUIREMENTS=Path(tmp)/'requirements.json'
                M.REQUIREMENTS.write_text(json.dumps(data))
                with self.assertRaises(ValueError):M.requirements()
        finally:M.REQUIREMENTS=original
    def test_runner_refuses_a_missing_uvm_library_and_an_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=str(Path(M.__file__))
            self.assertEqual(subprocess.run([sys.executable,script,'--uvm-home',tmp,'--out',str(Path(tmp)/'new')],capture_output=True).returncode,2)
            self.assertEqual(subprocess.run([sys.executable,script,'--uvm-home',tmp,'--out',tmp],capture_output=True).returncode,2)
if __name__=='__main__':unittest.main()
