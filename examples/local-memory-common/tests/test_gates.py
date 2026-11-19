"""A clean HDL exit alone cannot satisfy count, waveform and catalog gates."""
import importlib.util
from pathlib import Path
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('memory_gate_fifo',HERE.parent/'local-sync-ram-fifo/run.py')
R=importlib.util.module_from_spec(s);s.loader.exec_module(R)


class GateTests(unittest.TestCase):
    def run_wrapper(self,directory,extra,filter_wave=False,waves=False):
        tool=directory/'wrapped-vvp'
        body=('import subprocess,sys\nargs=sys.argv[1:]\n'
              +("args=[a for a in args if not a.startswith('+WAVE=')]\n" if filter_wave else '')
              +"r=subprocess.run(['vvp',*args])\n"+extra+'\nsys.exit(r.returncode)\n')
        tool.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -c '+shlex.quote(body)+' "$@"\n')
        tool.chmod(0o755)
        args=SimpleNamespace(iverilog='iverilog',vvp=str(tool),timeout=30,waves=waves)
        case=R.cases(SimpleNamespace(seed=17,profile='smoke'))[0]
        return R.S.Simulator(R,args,directory).execute(case)

    def test_duplicate_completion_count_rejected_after_real_hdl_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.run_wrapper(Path(tmp),"print('COUNT steps=128')")
            self.assertEqual(result['status'],'error',result)

    def test_missing_waveform_rejected_after_real_hdl_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self.run_wrapper(Path(tmp),'',filter_wave=True,waves=True)
            self.assertEqual(result['status'],'error',result)

    def test_catalog_and_runner_goal_drift_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(out=Path(tmp)/'out')
            old=R.GOALS
            try:
                R.GOALS=old|{'never/observed'}
                with self.assertRaisesRegex(ValueError,'catalog'):R.S.run(R,args)
                self.assertFalse(args.out.exists())
            finally:R.GOALS=old


if __name__=='__main__':unittest.main()
