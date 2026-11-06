"""Shared bounded simulation/evidence support for image IP and image SoC examples."""
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


E = load('image_evidence', HERE.parent/'local-exploration-common/evidence.py')
MODEL = load('image_oracle', HERE/'model.py')


def validate_completion(directory, output, observed, scenario, soc):
    total=sum(map(len,output))
    expected=dict(pixels=total,frames=len(output))
    if soc:
        expected.update(cpu_checks=0 if scenario in (1,2) else total,irqs=len(output)+9*int(scenario==3),resets=int(scenario in (5,6)))
        memory=[int(line,16) for line in (directory/'ram-readback.hex').read_text().splitlines()]
        if memory != [0xa5a50000|value for frame in output for value in frame]:raise ValueError('RAM readback differs from whole-frame oracle')
        if not (directory/'retirement.log').read_text().strip():raise ValueError('retirement trace missing')
    else:expected.update(accepted=total,resets=int(scenario==1))
    if observed!=expected:raise ValueError('completion counts differ: '+str(observed)+' expected '+str(expected))


class Simulator:
    def __init__(self, evidence, top, sources):
        self.e = evidence
        self.top = top
        self.sources = sources
        self.builds = {}
        self.records = []

    def execute(self, name, parameters, frames, seed, mutation=0, expected=None, scenario=0, firmware=None, plusargs=None):
        d = self.e.out/name
        d.mkdir(parents=True)
        width, height = parameters['W'], parameters['H']
        output = [MODEL.sobel(frame, width, height) for frame in frames]
        for filename, values in (('pixels.hex', frames), ('expected.hex', output)):
            (d/filename).write_text(''.join(f'{v:02x}\n' for frame in values for v in frame))
        if firmware is not None:
            (d/'rom.hex').write_text(''.join(f'{word:08x}\n' for word in firmware))
        inputs=[d/'pixels.hex',d/'expected.hex']+([d/'rom.hex'] if firmware is not None else [])
        E.P.write_json(d/'manifest.json',dict(parameters=parameters,seed=seed,scenario=scenario,mutation=mutation,
            frames=len(frames),expected_failure=expected,
            source_sha256={str(p):E.hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}))
        key = '-'.join(f'{k}{v}' for k, v in sorted(dict(parameters, MUTATION=mutation).items()))
        if key not in self.builds:
            binary = self.e.out/(key+'.vvp')
            command = [self.e.args.iverilog, '-g2012', '-s', self.top, '-o', str(binary)]
            command += [f'-P{self.top}.{k}={v}' for k, v in dict(parameters, MUTATION=mutation).items()]
            command += list(map(str, self.sources))
            self.builds[key] = binary, E.P.execute(command, self.e.out/(key+'-build.log'), self.e.args.timeout, self.e.out)
        binary, build = self.builds[key]
        command = [self.e.args.vvp, str(binary), '+INPUT='+str(d/'pixels.hex'), '+EXPECTED='+str(d/'expected.hex'),
                   '+ROM='+str(d/'rom.hex'), '+WAVE='+str(d/'trace.vcd'), '+TRACE='+str(d/'retirement.log'),
                   '+RAMFILE='+str(d/'ram-readback.hex'),
                   f'+FRAMES={len(frames)}', f'+SEED={seed}', f'+SCENARIO={scenario}', *[f'+{k}={v}' for k, v in (plusargs or {}).items()]]
        if build['error'] or build['returncode'] != 0:
            execution = dict(returncode=None, error='build failed; see '+key+'-build.log', seconds=0)
            (d/'simulation.log').write_text(execution['error']+'\n')
        else:
            execution = E.P.execute(command, d/'simulation.log', self.e.args.timeout, d)
        log = (d/'simulation.log').read_text(errors='replace')
        status, message = E.P.classify(dict(checks=width*height*len(frames), expected_failure=expected), execution, log)
        counts = re.findall(r'^COUNT ([a-z_]+)=(\d+)$', log, re.M)
        observed = dict((k, int(v)) for k, v in counts)
        if status == 'pass':
            try:
                if len(counts)!=len(observed):raise ValueError('duplicate completion counts')
                validate_completion(d,output,observed,scenario,firmware is not None)
            except (OSError,ValueError) as exc:status,message='error',str(exc)
        wave = d/'trace.vcd'
        if status in ('pass', 'detected') and (not wave.is_file() or '$enddefinitions' not in wave.read_text()):
            status, message = 'error', 'waveform missing'
        record = dict(id=name, status=status, message=message, parameters=parameters, mutation=mutation, scenario=scenario,
                      seed=seed, frames=len(frames), counts=observed, expected_failure=expected,
                      coverage=sorted(set(re.findall(r'^COVER (\S+)$', log, re.M))) if status == 'pass' and mutation == 0 else [], execution=execution)
        E.P.write_json(d/'result.json', record)
        self.records.append(record)
        self.e.check(name, status in ('pass', 'detected'), record)
        return record

    def save(self):
        E.P.write_json(self.e.out/'executions.json', self.records)
        E.P.write_json(self.e.out/'builds.json', {k:dict(binary=str(v[0]), execution=v[1]) for k,v in self.builds.items()})


def fresh(evidence):
    frozen = json.loads((evidence.out/'manifest.json').read_text())['source_sha256']
    changed = [name for name, value in frozen.items() if not (ROOT/name).is_file() or E.hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != value]
    evidence.check('source-freshness', not changed, changed)
