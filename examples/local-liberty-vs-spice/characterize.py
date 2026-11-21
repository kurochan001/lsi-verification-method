#!/usr/bin/env python3
"""Measure the flip-flop once and write a new table and Liberty file to a directory.

Not part of the regression. Use it after changing the circuit on purpose, read the
difference, and only then copy the two files over the checked-in ones.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('liberty_vs_spice_run', HERE / 'run.py')
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)
MODEL = RUN.MODEL
AXES = dict(schema_version=1, units=dict(time='ps', capacitance='fF'),
            clock_slew_ps=[10, 50, 100], load_ff=[10, 50, 100], delay_data_slew_ps=50,
            data_slew_ps=[10, 100], clock_slew_check_ps=[10, 100], check_load_ff=20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ngspice-config', default='lsi-ngspice-config')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    prefix = subprocess.run([args.ngspice_config, '--prefix'], check=True, capture_output=True, text=True).stdout.strip()
    jobs = RUN.delay_jobs(AXES) + RUN.check_jobs(AXES)
    (args.out / 'jobs.json').write_text(json.dumps(jobs))
    subprocess.run([sys.executable, str(HERE / 'measure.py'), prefix, str(args.out / 'jobs.json'),
                    str(args.out / 'results.json')], check=True)
    results = RUN.read_results(args.out / 'results.json', jobs)
    table = dict(AXES)
    for group in (MODEL.measured_delays(results, AXES), MODEL.measured_checks(results, AXES)):
        for name, rows in group.items():
            table[name] = [[round(v, 2) for v in row] for row in rows]
    MODEL.validate_table(table)
    (args.out / 'characterized.json').write_text(json.dumps(table, indent=2) + '\n')
    (args.out / 'ff_measured.lib').write_text(MODEL.liberty(table))
    print('wrote', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
