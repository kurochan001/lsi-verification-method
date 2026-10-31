"""Bounded processes and fail-closed JSON/JUnit evidence for repository tools."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent.parent
PROCESS=ROOT/'examples/local-irq-cdc/run.py'
s=importlib.util.spec_from_file_location('quality_process',PROCESS);P=importlib.util.module_from_spec(s);s.loader.exec_module(P)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def executable(value):
    found=shutil.which(str(value))
    return str(Path(found).absolute()) if found else str(value)
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
class Report:
    def __init__(self,name,out,inputs,checks,options=None):
        self.name=name;self.out=Path(out).absolute();self.out.mkdir(parents=True,exist_ok=False)
        self.checks=list(checks);self.results=[]
        if not self.checks or len(self.checks)!=len(set(self.checks)):raise ValueError('empty/duplicate check plan')
        paths={Path(__file__),PROCESS,*map(Path,inputs)}
        self.sources={str(p.absolute()):digest(p) for p in sorted(paths)}
        write(self.out/'manifest.json',dict(name=name,python=sys.version,check_ids=self.checks,options=options or {},source_sha256=self.sources))
    def check(self,name,success,detail):
        if name not in self.checks or any(r['id']==name for r in self.results):raise ValueError('unplanned/duplicate check: '+name)
        self.results.append(dict(id=name,status='pass' if success else 'fail',detail=detail));return success
    def fresh(self):return [p for p,h in self.sources.items() if not Path(p).is_file() or digest(p)!=h]
    def finish(self):
        complete={r['id'] for r in self.results}==set(self.checks)
        for name in self.checks:
            if not any(r['id']==name for r in self.results):self.check(name,False,'planned check did not complete')
        success=complete and all(r['status']=='pass' for r in self.results)
        write(self.out/'summary.json',dict(success=success,complete=complete,planned=len(self.checks),results=self.results))
        suite=ET.Element('testsuite',name=self.name,tests=str(len(self.results)),failures=str(sum(r['status']=='fail' for r in self.results)),errors='0')
        for r in self.results:
            c=ET.SubElement(suite,'testcase',name=r['id'],classname=self.name)
            if r['status']!='pass':ET.SubElement(c,'failure',message=str(r['detail']))
        ET.indent(suite);ET.ElementTree(suite).write(self.out/'junit.xml',encoding='utf-8',xml_declaration=True)
        print(self.name+': '+('PASS' if success else 'FAIL')+f' ({len(self.results)} checks)');print('Artifacts:',self.out)
        return 0 if success else 1
