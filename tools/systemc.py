"""Snapshot the installed SystemC headers and static library used by CABA examples."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def snapshot(home):
    home=Path(home).resolve()
    files=[home/'include/systemc',home/'include/systemc.h',home/'lib/libsystemc.a',home/'bin/lsi-systemc-config',*sorted((home/'include/sysc').rglob('*'))]
    files=[p for p in files if not p.is_dir()]
    if len(files)<10 or any(not p.is_file() for p in files):raise ValueError('incomplete SystemC installation')
    spec=json.loads((HERE/'environment.json').read_text())['native_sources']['systemc']
    return dict(root=str(home),release=spec['release'],source_commit=spec['commit'],sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)})
def verify(record):
    current=snapshot(record['root'])
    if current!=record:raise ValueError('SystemC installation changed')
    return current
