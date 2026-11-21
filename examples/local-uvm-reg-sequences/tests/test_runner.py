import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
HERE = Path(__file__).resolve().parents[1]
S = importlib.util.spec_from_file_location('reg_sequences_test_runner', HERE / 'run.py')
R = importlib.util.module_from_spec(S)
S.loader.exec_module(R)
M = R.M
HEADER = ['Accellera:1800.2:UVM:2020.3.2', 'UVM_WARNING x [NO_DPI_USED] x', 'UVM_WARNING x [NO_VISIT_CHECK] x']


def synthetic_log(c, extra_warnings=0):
    """A log that follows the plan of one case, with values that satisfy the specification."""
    plan = M.expected_counts(c['iterations'], **c['model'])
    lines = [*HEADER, *['UVM_WARNING x [uvm_reg_access_seq] x'] * extra_warnings, 'REGLOG RST']
    age = 0
    state = {0x00: 0xa5, 0x04: M.ID_VALUE, 0x0c: 0, 0x10: 0, 0x14: 0}
    for stage, accesses in plan.items():
        lines.append('STAGE ' + stage)
        for write in (1, 0):
            for (address, is_write), count in sorted(accesses.items()):
                if is_write != write:
                    continue
                for _ in range(count):
                    age += 3
                    mapped = address in state or address == 0x08 or M.MEMORY_BASE <= address < 0x80
                    value = age & 0xff if address == 0x08 else state.get(address, 0)
                    # Writes repeat the current value, so the state never changes.
                    lines.append(f'REGLOG BUS age={age} w={write} addr={address:x} wdata={0 if address in (0x08, 0x0c, 0x14) else value:x} rdata={value:x} err={int(not mapped)} ev=0')
    lines.append('STAGE done')
    if c['coverage']:
        lines += ['COVER ' + g for g in sorted(R.GOALS)]
    else:
        lines += ['COVER ' + g for g in sorted(R.GOALS) if not g.startswith('ral/')]
    lines += [f'COUNT {k}={v}' for k, v in c['totals'].items()]
    lines.append(f"RESULT PASS checks={c['checks']}")
    lines += [f"UVM_WARNING : {len(c['warnings'])}", 'UVM_ERROR : 0', 'UVM_FATAL : 0']
    return '\n'.join(lines) + '\n'


OK = dict(error=None, returncode=0)


class PlanTests(unittest.TestCase):
    def test_default_plan_totals_follow_the_register_table(self):
        plan = M.expected_counts(4)
        # 152 tested bits (five full words minus the volatile byte, plus 31 bits beside the WO bit).
        self.assertEqual(sum(plan['bit_bash'].values()), 4 * (32 * 4 + 24 + 31))
        self.assertEqual(sum(plan['hw_reset'].values()), 5)
        self.assertEqual(sum(plan['mem_walk'].values()), 31 + 16)
        self.assertEqual(sum(plan['unmapped'].values()), 2 * 42)
        self.assertEqual(M.totals(plan), dict(reads=504, writes=482, errors=84))

    def test_volatility_exclusion_and_backdoor_change_the_plan(self):
        base = M.expected_counts(4, builtin_only=True)
        stable = M.expected_counts(4, builtin_only=True, status_volatile=False)
        self.assertEqual(stable['hw_reset'][(0x08, 0)], 1)
        self.assertNotIn((0x08, 0), base['hw_reset'])
        self.assertEqual(stable['bit_bash'][(0x08, 1)], 64)
        self.assertEqual(base['bit_bash'][(0x08, 1)], 48)
        self.assertEqual(base['bit_bash'][(0x14, 1)], 62)
        self.assertNotIn((0x0c, 1), M.expected_counts(4, builtin_only=True, bit_bash_excluded=['irq'])['bit_bash'])
        hidden = M.expected_counts(4, builtin_only=True, excluded=['scratch'])
        self.assertFalse(any(a == 0x10 for stage in ('hw_reset', 'access', 'bit_bash') for a, _ in hidden[stage]))
        self.assertEqual(hidden['preload'][(0x10, 1)], 1)
        self.assertEqual(M.expected_counts(4, backdoor=False)['access'], {})
        self.assertNotIn('mem_unique', base)

    def test_case_plan_has_fixed_size_unique_ids_and_planned_labels(self):
        for profile, size in (('smoke', 23), ('nightly', 25)):
            seeds, _, plan = R.cases(profile, 17)
            ids = [c['id'] for c in plan]
            self.assertEqual((len(ids), len(set(ids))), (size, size))
            self.assertEqual(len(seeds), 1 if profile == 'smoke' else 3)
        labels = {c['id']: c['expected_failure'] for c in plan}
        self.assertEqual({labels[f'mutation{m}'] for m in R.MUTANTS}, set(R.MUTANTS.values()))
        self.assertTrue(all(labels[f'builtin-only-mutation{m}'] is None for m in R.BUILTIN_MISSES))
        self.assertIsNone(labels['over-exclusion-mutation2'])

    def test_sources_agree_with_the_runner_tables(self):
        rtl = (HERE / 'rtl/reg_bank.sv').read_text()
        self.assertEqual({int(m) for m in re.findall(r'MUTATION == (\d+)', rtl)}, set(R.MUTANTS))
        bench = (HERE / 'tb/reg_seq_pkg.sv').read_text() + (HERE / 'tb/top.sv').read_text()
        for label in {*R.MUTANTS.values(), 'REG_ACCESS'}:
            self.assertIn('"' + label + '"', bench)
        for goal in R.GOALS:
            if not goal.startswith('ral/'):
                self.assertIn('COVER ' + goal, bench)
        self.assertEqual(len(R.GOALS), 34)
        self.assertEqual(len(M.UNMAPPED), 42)


class ReplayTests(unittest.TestCase):
    def replay(self, *lines):
        return M.replay('\n'.join(['REGLOG RST', 'STAGE t', *lines]) + '\n')

    def bus(self, age, write, address, wdata, rdata, error=0, ev=0):
        return f'REGLOG BUS age={age} w={write} addr={address:x} wdata={wdata:x} rdata={rdata:x} err={error} ev={ev:x}'

    def test_reset_values_status_counter_and_write_readback(self):
        self.replay(self.bus(3, 0, 0x00, 0, 0xa5), self.bus(6, 0, 0x04, 0, M.ID_VALUE), self.bus(300, 0, 0x08, 0, 300 & 0xff),
                    self.bus(303, 1, 0x00, 0x1234, 0), self.bus(306, 0, 0x00, 0, 0x34), self.bus(309, 1, 0x04, 0, 0), self.bus(312, 0, 0x04, 0, M.ID_VALUE))
        for bad in (self.bus(3, 0, 0x00, 0, 0xa4), self.bus(3, 0, 0x08, 0, 4), self.bus(3, 0, 0x14, 0, 1)):
            with self.assertRaises(ValueError):
                self.replay(bad)

    def test_w1c_event_wins_and_soft_reset(self):
        self.replay('REGLOG EVT age=2 ev=f', self.bus(5, 0, 0x0c, 0, 0xf), self.bus(8, 1, 0x0c, 0x5, 0, ev=1), self.bus(11, 0, 0x0c, 0, 0xb),
                    self.bus(14, 1, 0x10, 0x77, 0), self.bus(17, 1, 0x14, 1, 0, ev=2), self.bus(20, 0, 0x0c, 0, 0), self.bus(23, 0, 0x10, 0, 0))
        with self.assertRaises(ValueError):
            self.replay('REGLOG EVT age=2 ev=f', self.bus(5, 1, 0x0c, 0x4, 0), self.bus(8, 0, 0x0c, 0, 0xf))
        with self.assertRaises(ValueError):
            self.replay(self.bus(5, 1, 0x10, 0x77, 0), self.bus(8, 1, 0x14, 1, 0), self.bus(11, 0, 0x10, 0, 0x77))

    def test_memory_unmapped_addresses_and_deposits(self):
        self.replay(self.bus(3, 1, 0x44, 0xdead, 0), self.bus(6, 0, 0x44, 0, 0xdead), self.bus(9, 1, 0x90, 1, 0, error=1), self.bus(12, 0, 0x18, 0, 0, error=1),
                    'REGLOG POKE target=1 value=55', self.bus(15, 0, 0x10, 0, 0x55), 'REGLOG POKE target=0 value=1ff', self.bus(18, 0, 0x00, 0, 0xff))
        for bad in ([self.bus(3, 0, 0x40, 0, 0)], [self.bus(3, 1, 0x90, 1, 0)], [self.bus(3, 0, 0x44, 0, 0, error=1)],
                    [self.bus(3, 1, 0x40, 1, 0), self.bus(6, 1, 0x60, 2, 0), self.bus(9, 0, 0x40, 0, 2)]):
            with self.assertRaises(ValueError):
                self.replay(*bad)

    def test_malformed_or_unordered_records_are_rejected(self):
        for lines in ([self.bus(6, 0, 0x00, 0, 0xa5), self.bus(6, 0, 0x00, 0, 0xa5)], ['REGLOG BUS age=x'], ['REGLOG EVT age=3 ev=0'], ['STAGE t']):
            with self.assertRaises(ValueError):
                self.replay(*lines)
        with self.assertRaises(ValueError):
            M.replay('STAGE t\n' + self.bus(3, 0, 0x00, 0, 0xa5) + '\n')


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        _, _, plan = R.cases('smoke', 17)
        self.cases = {c['id']: c for c in plan}

    def test_complete_log_passes_and_each_missing_piece_fails(self):
        c = self.cases['seed17']
        log = synthetic_log(c)
        ok, message, details = R.evaluate(c, OK, log)
        self.assertTrue(ok, message)
        self.assertEqual(details['accesses']['bit_bash'], 732)
        first_read = next(l for l in log.splitlines() if l.startswith('REGLOG BUS') and ' w=0 addr=0 ' in l)
        for text in (log.replace('2020.3.2', '2017.1.0'), log.replace('UVM_ERROR : 0', 'UVM_ERROR : 1'), log.replace('COUNT errors=84', 'COUNT errors=0'),
                     log.replace(first_read + '\n', '', 1), log.replace(first_read, first_read.replace('rdata=a5', 'rdata=a4'), 1),
                     log + 'COVER unknown/goal\n', log + 'RAL_SAMPLE_OUTSIDE offset=84\n', log + 'UVM_WARNING x [RegModel] x\n',
                     log.replace('RESULT PASS checks=986', 'RESULT PASS checks=985'), log.replace('STAGE mem_unique\n', '')):
            self.assertFalse(R.evaluate(c, OK, text)[0])
        self.assertTrue(R.evaluate(c, OK, log + 'RAL_SAMPLE_OUTSIDE offset=80\nCOVER ral/value/id/other\n')[0])

    def test_variant_plans_are_checked_against_their_own_counts(self):
        for name, warnings in (('builtin-only-mutation5', 0), ('over-exclusion-mutation2', 0), ('events-during-bash-excluded', 0),
                               ('status-nonvolatile-excluded', 0), ('backdoor-none', 2), ('coverage-off', 0)):
            c = self.cases[name]
            ok, message, _ = R.evaluate(c, OK, synthetic_log(c, warnings))
            self.assertTrue(ok, name + ': ' + message)
        # The default plan is not accepted where a register was excluded, and the reverse.
        self.assertFalse(R.evaluate(self.cases['seed17'], OK, synthetic_log(self.cases['status-nonvolatile-excluded']))[0])
        self.assertFalse(R.evaluate(self.cases['backdoor-none'], OK, synthetic_log(self.cases['backdoor-none'], 0))[0])
        self.assertFalse(R.evaluate(self.cases['coverage-off'], OK, synthetic_log(self.cases['seed17']))[0])

    def test_detection_needs_the_planned_label_and_library_report(self):
        c = self.cases['mutation2']
        failed = dict(error=None, returncode=1)
        self.assertTrue(R.evaluate(c, failed, 'LIBRARY_REPORT id=uvm_reg_bit_bash_seq message=x\nCHECK_FAIL REG_BITBASH\n')[0])
        self.assertFalse(R.evaluate(c, failed, 'unrelated crash\n')[0])
        self.assertFalse(R.evaluate(c, failed, 'CHECK_FAIL REG_RESET\n')[0])
        self.assertFalse(R.evaluate(c, OK, synthetic_log(self.cases['seed17']))[0])
        hdl = self.cases['backdoor-hdl-path']
        self.assertTrue(R.evaluate(hdl, failed, 'LIBRARY_REPORT id=UVM_HDL_READ message=x\nCHECK_FAIL REG_ACCESS\n')[0])
        self.assertFalse(R.evaluate(hdl, failed, 'LIBRARY_REPORT id=RegModel message=x\nCHECK_FAIL REG_ACCESS\n')[0])
        self.assertFalse(R.evaluate(hdl, dict(error='timeout', returncode=None), 'CHECK_FAIL REG_ACCESS\n')[0])

    def test_survivors_must_complete_cleanly(self):
        c = self.cases['builtin-only-mutation7']
        self.assertFalse(R.evaluate(c, dict(error=None, returncode=1), 'CHECK_FAIL REG_W1C\n')[0])


class CoverageDatabaseTests(unittest.TestCase):
    def line(self, name, count, kind='covergroup', file='tb/reg_seq_pkg.sv', group='value_classes'):
        meta = dict(t=kind, page='v_covergroup/x', f=file, l='1', n='1', bin=name, h=f'__vlAnonCG_{group}.value_class.{name}')
        return "C '" + ''.join(f'\x01{k}\x02{v}' for k, v in meta.items()) + f"' {count}\n"

    def test_bins_are_read_and_identity_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'coverage.dat'
            p.write_text('# header\n' + self.line('zero', 3) + self.line('ones', 0) + self.line('other', 9) + self.line('ignored', 1, kind='line'))
            self.assertEqual(R.native_bins(p), dict(zero=3, ones=0, other=9))
            for text in (self.line('zero', 3) + self.line('ones', 1), self.line('zero', 1) * 2 + self.line('ones', 1) + self.line('other', 1),
                         self.line('zero', 1, file='other.sv') + self.line('ones', 1) + self.line('other', 1),
                         self.line('zero', 1, group='different') + self.line('ones', 1) + self.line('other', 1), '# no counters\n'):
                p.write_text(text)
                with self.assertRaises(ValueError):
                    R.native_bins(p)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / 'run.py'), *args], capture_output=True, text=True, timeout=60)

    def test_missing_library_and_existing_output_are_usage_errors(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli('--uvm-home', d, '--out', str(Path(d) / 'new')).returncode, 2)
            self.assertFalse((Path(d) / 'new').exists())
            (Path(d) / 'src').mkdir()
            (Path(d) / 'src/uvm_pkg.sv').write_text('')
            self.assertEqual(self.run_cli('--uvm-home', d, '--out', d).returncode, 2)
            self.assertEqual(self.run_cli('--uvm-home', d, '--out', str(Path(d) / 'new'), '--jobs', '0').returncode, 2)

    def test_failed_build_fails_every_planned_case_without_running(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'src').mkdir()
            (Path(d) / 'src/uvm_pkg.sv').write_text('')
            tool = Path(d) / 'verilator'
            tool.write_text('#!/bin/sh\nexit 3\n')
            tool.chmod(0o755)
            r = self.run_cli('--uvm-home', d, '--verilator', str(tool), '--out', str(Path(d) / 'out'))
            self.assertEqual(r.returncode, 1)
            self.assertIn('FAIL build', r.stdout)
            self.assertNotIn('PASS mutation', r.stdout)
            self.assertEqual(r.stdout.count('FAIL '), 25)


if __name__ == '__main__':
    unittest.main()
