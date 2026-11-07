from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_tb_races as C

BLOCK='always @(posedge clk) begin count=count+1; end\n'


class TestbenchRaceTests(unittest.TestCase):
    def reasons(self,text,headers=None):
        return [(name,reason) for _,name,reason in C.find_races(text,headers)]

    def test_each_kind_of_reader_is_found(self):
        cases={
            'read by a continuous assignment':'wire full;assign full=count==3;\n',
            'read by a net declaration':'wire full=count==3;\n',
            'in a port connection':'ram u(.clk(clk),.addr(count));\n',
            'read by another block on the same edge':'always @(posedge clk) if(count==3) done<=1;\n',
        }
        for reason,reader in cases.items():
            with self.subTest(reason=reason):self.assertEqual(self.reasons(BLOCK+reader),[('count',reason)])

    def test_an_implicit_port_is_found_through_the_module_header(self):
        instance='ram #(.N(2)) u(.*);\n'
        self.assertEqual(self.reasons(BLOCK+instance,dict(ram='(input wire clk,input wire [3:0] count)')),[('count','in an implicit port connection')])
        self.assertEqual(self.reasons(BLOCK+instance,dict(ram='(input wire clk,input wire [3:0] other)')),[])
        self.assertEqual(self.reasons(BLOCK+instance,{}),[])

    def test_the_races_fixed_on_2026_11_07_are_found(self):
        # The shape of the old local-dma bench: a blocking counter read by a declared net.
        self.assertIn(('cycles','read by a net declaration'),self.reasons(
            'integer cycles=0;wire permit=cycles%3==2;\nalways @(posedge clk) begin\n  cycles=cycles+1;\nend\n'))

    def test_safe_shapes_are_left_alone(self):
        for name,text in {
            'nonblocking':'always @(posedge clk) count<=count+1;\nwire full=count==3;\n',
            'read in its own block':'always @(posedge clk) begin count=count+1;if(count==3)done<=1;end\n',
            'read on another edge':BLOCK+'always @(negedge clk) if(count==3) done<=1;\n',
            'a loop variable':'always @(posedge clk) begin for(i=0;i<4;i=i+1)mem[i]<=0;end\nwire x=i==0;\n',
            'a comparison':'always @(posedge clk) if(count==3 && count!=4) done<=1;\nwire full=count==3;\n',
            'in a comment':'// always @(posedge clk) count=1;\nwire full=count==3;\n',
        }.items():
            with self.subTest(name):self.assertEqual(self.reasons(text),[])

    def test_the_testbenches_in_this_repository_have_no_such_race(self):
        self.assertGreater(len(C.testbenches(C.ROOT)),100)
        self.assertEqual(C.scan(),[])


if __name__=='__main__':unittest.main()
