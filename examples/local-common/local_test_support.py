"""Utilities for local example self-tests (not imported by the regressions)."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

EXAMPLES=Path(__file__).resolve().parent.parent


def load_example(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),EXAMPLES/name/'run.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_example(name,out,*options):
    return subprocess.run([sys.executable,str(EXAMPLES/name/'run.py'),'--out',str(out),*options],
                          capture_output=True,text=True,timeout=90)


def read_json(path):
    return json.loads(path.read_text())


def assert_evidence(test,out,configurations,goal_count,executions,diagnostics=0):
    summary=read_json(out/'summary.json')
    test.assertTrue(summary['success'],summary)
    test.assertTrue(summary['complete'])
    test.assertEqual(summary['planned'],executions)
    test.assertEqual(summary['results'],executions)
    test.assertEqual(summary['mutations_detected'],4*len(configurations))
    test.assertEqual(summary['diagnostics_pass'],diagnostics)
    coverage=read_json(out/'coverage.json')
    test.assertEqual(set(coverage),set(configurations))
    for item in coverage.values():
        test.assertTrue(item['success'])
        test.assertEqual(item['hit'],goal_count)
        test.assertEqual(item['missing'],[])
    import xml.etree.ElementTree as ET
    suite=ET.parse(out/'junit.xml').getroot()
    test.assertEqual(int(suite.get('tests')),executions+len(configurations))
    test.assertEqual(suite.get('failures'),'0')
    test.assertEqual(suite.get('errors'),'0')
    names=[(node.get('classname'),node.get('name')) for node in suite.findall('testcase')]
    test.assertEqual(len(names),len(set(names)))
    for result in out.glob('*/result.json'):
        record=read_json(result)
        if record['category']!='functional':test.assertEqual(record['credited_coverage'],[])
        wave=result.parent/'wave.vcd'
        test.assertTrue(wave.exists(),str(wave))
        test.assertIn('$enddefinitions',wave.read_text())


def simulate_vectors(example, rows, parameters=None, replacements=None):
    """Compile real RTL with targeted vectors; optional source edits test the checker."""
    import shutil
    import tempfile
    import unittest
    if not (shutil.which('iverilog') and shutil.which('vvp')):
        raise unittest.SkipTest('Icarus required')
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);sources=[]
        for index, source in enumerate(example.SOURCES):
            edits=(replacements or {}).get(source.name,[])
            if edits:
                content=source.read_text()
                for old,new in edits:
                    if old not in content:raise ValueError(f'Edit target missing in {source}: {old}')
                    content=content.replace(old,new)
                source=out/f'{index}-{source.name}';source.write_text(content)
            sources.append(str(source))
        vectors=out/'vectors.txt'
        vectors.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in rows))
        parameters=parameters or next(iter(example.CONFIGS.values()))
        command=['iverilog','-g2012','-s',example.TOP,'-o',str(out/'sim.vvp'),f'-P{example.TOP}.MUTATION=0']
        command += [f'-P{example.TOP}.{key}={value}' for key,value in parameters.items()]+sources
        subprocess.run(command,capture_output=True,text=True,timeout=30,check=True)
        return subprocess.run(['vvp',str(out/'sim.vvp'),f'+VECTORS={vectors}',f'+WAVE={out / "wave.vcd"}'],
                              capture_output=True,text=True,timeout=30)
