"""One isolated cocotb execution. Simulator failures are checked by the parent too."""
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from cocotb_tools.runner import get_runner
case_path=Path(sys.argv[1]).resolve();case=json.loads(case_path.read_text());out=case_path.parent
# The runner API resolves Icarus tools by PATH. Require the requested pair to be co-located.
iverilog=Path(__import__('shutil').which(sys.argv[2]) or sys.argv[2]).resolve()
vvp=Path(__import__('shutil').which(sys.argv[3]) or sys.argv[3]).resolve()
if not iverilog.is_file() or not vvp.is_file() or iverilog.name!='iverilog' or vvp.name!='vvp':raise ValueError('requested Icarus executables are missing or have unsupported names')
if iverilog.parent!=vvp.parent:raise ValueError('Icarus and vvp must be in one tool directory')
os.environ['PATH']=str(iverilog.parent)+os.pathsep+os.environ['PATH']
here=Path(__file__).resolve().parent
runner=get_runner('icarus')
runner.build(sources=[here.parent/'gitlab-apb/rtl/apb_regs.sv'],hdl_toplevel='apb_regs',parameters=dict(WAIT_CYCLES=case['wait'],MUTATION=case['mutation']),build_dir=out/'build',always=True,waves=True,timescale=("1ns","1ps"))
runner.test(hdl_toplevel='apb_regs',test_module='test_apb',test_dir=out,build_dir=out/'build',results_xml=out/'cocotb-junit.xml',waves=True,seed=case['seed'],extra_env={'CASE_JSON':str(case_path),'PYTHONPATH':str(here)+os.pathsep+os.environ.get('PYTHONPATH','')})
root=ET.parse(out/'cocotb-junit.xml').getroot();nodes=list(root.iter('testcase'))
if len(nodes)!=1 or any(list(n.iter('failure')) or list(n.iter('error')) for n in nodes):sys.exit(1)
