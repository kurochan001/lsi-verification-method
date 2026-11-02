"""Pinned ngspice shared-library provenance and a real, analytic RC smoke probe."""
import ctypes as C
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
import re
import shutil
import sys

HERE=Path(__file__).resolve().parent
CONFIG=HERE/'ngspice.json'
MARKER=Path('share/lsi-ngspice/build.json')
def spec():
    value=json.loads(CONFIG.read_text())
    if digest(HERE.parent/value['patch']['file'])!=value['patch']['sha256']:raise ValueError('ngspice patch digest differs')
    return value
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def library(home):
    return Path(home)/'lib'/('libngspice.dylib' if sys.platform=='darwin' else 'libngspice.so')
def files(home):
    home=Path(home).resolve()
    paths=[home/'include/ngspice/sharedspice.h',home/'bin/lsi-ngspice-config',home/'share/lsi-ngspice/COPYING',*sorted((home/'lib').glob('libngspice*'))]
    if len(paths)<4 or not library(home).is_file() or any(not p.is_file() or not p.resolve().is_relative_to(home) for p in paths):
        raise ValueError('incomplete or external ngspice installation')
    return {str(p.relative_to(home)):digest(p) for p in paths}

def record_install(home,source):
    home=Path(home).resolve();config=spec()
    if digest(Path(source)/config['patch']['target'])!=config['patch']['patched_sha256']:raise ValueError('ngspice source patch is missing')
    command=home/'bin/lsi-ngspice-config';command.parent.mkdir(parents=True,exist_ok=True)
    command.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\nroot=Path(__file__).resolve().parents[1]\nif sys.argv[1:]==["--prefix"]:print(root)\nelif sys.argv[1:]==["--version"]:print("ngspice '+config['release']+'")\nelse:raise SystemExit("use --prefix or --version")\n')
    command.chmod(0o755)
    marker=home/MARKER;marker.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(Path(source)/'COPYING',marker.parent/'COPYING')
    marker.write_text(json.dumps(dict(spec=config,sha256=files(home)),indent=2)+'\n')
    return snapshot(home)

def snapshot(home):
    home=Path(home).resolve();marker=home/MARKER;record=json.loads(marker.read_text());observed=files(home)
    if record.get('spec')!=spec() or record.get('sha256')!=observed:raise ValueError('ngspice installation differs from pinned build record')
    return dict(root=str(home),release=spec()['release'],source_commit=spec()['commit'],library=str(library(home).resolve()),sha256={**observed,str(MARKER):digest(marker)})

def verify(record):
    current=snapshot(record['root'])
    if current!=record:raise ValueError('ngspice installation changed')
    return current

class Vector(C.Structure):
    _fields_=[('name',C.c_char_p),('kind',C.c_int),('flags',C.c_short),('real',C.POINTER(C.c_double)),('complex',C.c_void_p),('length',C.c_int)]

def probe(home):
    """Run once per subprocess, proving both init-file isolation and actual RC analysis."""
    record=snapshot(home)
    previous=Path.cwd()
    with tempfile.TemporaryDirectory(prefix='lsi-ngspice-probe-') as directory:
        Path(directory,'.spiceinit').write_text('echo Error: LSI_UNEXPECTED_USER_INIT\n')
        try:
            os.chdir(directory)
            return _probe(record)
        finally:os.chdir(previous)

def _probe(record):
    lib=C.CDLL(record['library']);messages=[];exits=[]
    Text=C.CFUNCTYPE(C.c_int,C.c_char_p,C.c_int,C.c_void_p)
    Exit=C.CFUNCTYPE(C.c_int,C.c_int,C.c_bool,C.c_bool,C.c_int,C.c_void_p)
    @Text
    def text(message,identifier,userdata):messages.append(message.decode(errors='replace'));return 0
    @Exit
    def exited(status,unload,quit_exit,identifier,userdata):exits.append(status);return 0
    lib.ngSpice_nospinit.argtypes=[];lib.ngSpice_nospiceinit.argtypes=[]
    lib.ngSpice_nospinit();lib.ngSpice_nospiceinit()
    lib.ngSpice_Init.argtypes=[C.c_void_p]*7;lib.ngSpice_Init.restype=C.c_int
    if lib.ngSpice_Init(C.cast(text,C.c_void_p),None,C.cast(exited,C.c_void_p),None,None,None,None):raise ValueError('ngspice initialization failed')
    lib.ngSpice_Command.argtypes=[C.c_char_p];lib.ngSpice_Command.restype=C.c_int
    def command(value):
        if lib.ngSpice_Command(C.create_string_buffer(value.encode())):raise ValueError('ngspice command failed: '+value)
    command('version')
    if not any(re.search(r'\bngspice-'+re.escape(spec()['release'])+r'\b',m) for m in messages):raise ValueError('actual ngspice API version differs')
    deck=['Independent RC probe','Vstep vin 0 DC 1','R1 vin vout 1000','C1 vout 0 100n ic=0','.options reltol=1e-7 abstol=1e-12 method=gear','.save v(vout)','.end']
    buffers=[C.create_string_buffer(line.encode()) for line in deck]
    array=(C.c_char_p*(len(buffers)+1))(*[C.cast(b,C.c_char_p) for b in buffers],None)
    lib.ngSpice_Circ.argtypes=[C.POINTER(C.c_char_p)];lib.ngSpice_Circ.restype=C.c_int
    if lib.ngSpice_Circ(array):raise ValueError('ngspice netlist failed')
    command('tran 5e-7 5e-4 0 5e-7 uic')
    lib.ngGet_Vec_Info.argtypes=[C.c_char_p];lib.ngGet_Vec_Info.restype=C.POINTER(Vector)
    vectors=[]
    for name in ('time','vout'):
        vector=lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
        if not vector or vector.contents.length<500 or not vector.contents.real:raise ValueError('ngspice RC trace missing')
        v=vector.contents
        vectors.append((v.length,v.real[v.length-1]))
    time,voltage=vectors
    if time[0]!=voltage[0]:raise ValueError('ngspice vector lengths differ')
    t=time[1];actual=voltage[1];expected=1-math.exp(-t/1e-4)
    if exits or any('error:' in m.lower() for m in messages) or not math.isfinite(actual) or abs(t-5e-4)>1e-12 or abs(actual-expected)>1e-4:
        raise ValueError('ngspice RC solution differs from analytic expectation: '+str((t,actual,expected,messages)))
    verify(record)
    return dict(success=True,release=record['release'],points=time[0],time=t,voltage=actual,expected=expected,error=abs(actual-expected),user_init_ignored=True,messages=messages)
