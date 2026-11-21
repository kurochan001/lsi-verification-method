import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE = Path(__file__).resolve().parents[1]
S = importlib.util.spec_from_file_location('reactive_runner', HERE / 'run.py')
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)
UVM = ('Accellera:1800.2:UVM:2020.3.2\nUVM_WARNING x [NO_DPI_USED] expected\nUVM_WARNING x [NO_VISIT_CHECK] expected\n'
       'UVM_WARNING : 2\nUVM_ERROR : 0\nUVM_FATAL : 0\n')


def synthesize(test, seed, shapes):
    """Write the log a correct requester and responder would produce for the given response shapes.
    It follows the documented cycle relations by hand and does not call the runner's model."""
    plan = M.planned_commands(test, seed, 0)
    lines = []
    memory = {}
    cycle = 6
    shapes = iter(shapes)
    counts = dict(commands=0, completed=0, cancelled=0, attempts=0, errors=0, timeouts=0, spurious=0, exhausted=0, retried_ok=0)
    items = 0

    def obs(kind, at, **f):
        v = dict(level=1, write=0, addr=0, wdata=0, rdata=0, err=0, timeout=0, tries=0)
        v.update(f)
        lines.append((at, f"RX_OBS kind={kind} cycle={at} " + ' '.join(f'{k}={v[k]}' for k in v)))
    obs(0, cycle)
    cycle += 3
    marks = dict(base={0: 'plain', 5: 'directed', 20: 'random,quiet', 24: 'deleted'}, error={0: 'directed', 4: 'random'})[test]
    for index, (write, addr, wdata, random) in enumerate(plan):
        for name in marks.get(index, '').split(','):
            if name:
                lines.append((cycle, f'RX_PHASE name={name} items={items}'))
        lines.append((cycle, f'RX_ISSUED n={index + 1} random={random} write={write} addr={addr} wdata={wdata}'))
        obs(4, cycle, write=write, addr=addr, wdata=wdata)
        counts['commands'] += 1
        start, penalty, tries = cycle, 0, 0
        while True:
            shape = dict(stall=0, delay=0, err=0, drop=0, early=0, dup=0, aborted=0)
            shape.update(next(shapes))
            if test == 'error':
                shape['err'] = int(addr >= 0xc0)
            tries += 1
            items += 1
            counts['attempts'] += 1
            accept = start + 2 + shape['stall'] + penalty
            if shape['early']:
                obs(2, start + 2, rdata=~addr & 255)
                counts['spurious'] += 1
            obs(3, accept, write=write, addr=addr, wdata=wdata)
            kind = 'rx_rsp_item' if test == 'base' else 'rx_err_item'
            item = f'RX_ITEM n={items} type={kind} write={write} addr={addr} ' + ' '.join(f'{k}={shape[k]}' for k in M.ITEM_FIELDS)
            if shape['aborted']:
                obs(0, accept + 3, level=0)
                obs(0, accept + 5)
                lines.append((accept + 4, item))
                counts['cancelled'] += 1
                cycle = accept + 8
                break
            if shape['drop']:
                lines.append((accept + 1, item))
                obs(1, accept + M.TIMEOUT + 1, err=1, timeout=1, tries=tries)
                counts['timeouts'] += 1
                counts['completed'] += 1
                cycle = accept + M.TIMEOUT + 1
                break
            rdata = 0 if write else memory.get(addr, ~addr & 255)
            response = accept + 1 + shape['delay']
            obs(2, response, err=shape['err'], rdata=rdata)
            lines.append((response, item))
            counts['errors'] += shape['err']
            final = not shape['err'] or tries == M.RETRIES + 1
            if final:
                obs(1, response + 1, err=shape['err'], rdata=rdata, tries=tries)
            if shape['dup']:
                obs(2, response + 1, rdata=~addr & 255)
                counts['spurious'] += 1
            if final:
                counts['completed'] += 1
                counts['exhausted'] += shape['err']
                counts['retried_ok'] += int(not shape['err'] and tries > 1)
                if write and not shape['err']:
                    memory[addr] = wdata
                cycle = response + 1 + shape['dup']
                break
            start, penalty = response, shape['dup']
    for name in marks.get(len(plan), '').split(','):
        if name:
            lines.append((cycle + 1, f'RX_PHASE name={name} items={items}'))
    lines.append((cycle + 1, f'RX_PHASE name=end items={items}'))
    lines.sort(key=lambda row: row[0])
    text = '\n'.join(line for _, line in lines) + '\n'
    return text + 'RX_COMPLETE ' + ' '.join(f'{k}={v}' for k, v in counts.items()) + f' items={items}\n', counts


def base_log(seed=17):
    quiet = [dict(stall=1, delay=2)] * 4
    return synthesize('base', seed, [{}] * 5 + M.DIRECTED_ITEMS + quiet + [{}] * 2)


def error_log(seed=17):
    return synthesize('error', seed, [{}] * 8)


class ReactiveRunnerTests(unittest.TestCase):
    def rejects(self, text, test='base'):
        with self.assertRaises(ValueError):
            M.ledger(text, test, 17, 0)

    def test_catalog_and_mutant_plan_are_complete(self):
        self.assertEqual(len(M.GOALS), 22)
        self.assertEqual(sorted(M.MUTANTS), list(range(1, 10)))
        self.assertEqual(len(M.DIRECTED_ITEMS), 21)
        self.assertEqual(len({d[0] for d in M.DIAGNOSTICS}), 5)

    def test_commands_follow_the_seed_and_the_address_set(self):
        self.assertEqual(len(M.planned_commands('base', 17, 40)), 66)
        self.assertEqual(len(M.planned_commands('error', 17, 40)), 44)
        self.assertEqual(M.issued_total('base', 400), 426)
        first = M.planned_commands('base', 17, 40)
        self.assertEqual(first, M.planned_commands('base', 17, 40))
        self.assertNotEqual(first, M.planned_commands('base', 18, 40))
        self.assertTrue(all(addr & 0x3c == 0 and random == 1 for _, addr, _, random in first[20:]))
        self.assertTrue(any(addr >= 0xc0 for _, addr, _, _ in M.planned_commands('error', 17, 40)))

    def test_base_log_is_accepted_and_scores_the_directed_goals(self):
        text, counts = base_log()
        result, goals = M.ledger(text, 'base', 17, 0)
        self.assertEqual({k: result[k] for k in counts}, counts)
        self.assertEqual((result['cancelled'], result['timeouts'], result['exhausted'], result['retried_ok'], result['spurious']), (1, 1, 1, 3, 3))
        expected = M.GOALS - {'factory/error-type', 'factory/error-region', 'callback/disable'}
        self.assertEqual(goals, expected)

    def test_error_log_is_accepted_and_scores_the_factory_goals(self):
        text, counts = error_log()
        result, goals = M.ledger(text, 'error', 17, 0)
        self.assertEqual((result['attempts'], result['errors'], result['exhausted'], result['ok']), (8, 6, 2, 2))
        self.assertLessEqual({'factory/error-type', 'factory/error-region'}, goals)
        self.assertNotIn('factory/base-type', goals)

    def test_wrong_read_data_and_wrong_completion_are_rejected(self):
        text, _ = base_log()
        lines = text.splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith('RX_OBS kind=2') and 'rdata=92 ' in line)
        self.rejects('\n'.join(lines[:index] + [lines[index].replace('rdata=92', 'rdata=93')] + lines[index + 1:]) + '\n')
        index = next(i for i, line in enumerate(lines) if line.startswith('RX_OBS kind=1') and 'tries=2' in line)
        self.rejects('\n'.join(lines[:index] + [lines[index].replace('tries=2', 'tries=1')] + lines[index + 1:]) + '\n')

    def test_cycle_relations_are_checked(self):
        text, _ = base_log()
        lines = text.splitlines()

        def shifted(prefix, needle, step):
            index = next(i for i, line in enumerate(lines) if line.startswith(prefix) and needle in line)
            cycle = int(lines[index].split()[2].split('=')[1])
            changed = list(lines)
            changed[index] = lines[index].replace(f'cycle={cycle} ', f'cycle={cycle + step} ')
            return '\n'.join(changed) + '\n'
        # A timeout one edge early, a late acceptance and a late response.
        self.rejects(shifted('RX_OBS kind=1', 'timeout=1', -1))
        self.rejects(shifted('RX_OBS kind=3', '', 1))
        self.rejects(shifted('RX_OBS kind=2', 'rdata=92 ', 1))

    def test_missing_extra_and_reordered_observations_are_rejected(self):
        text, _ = base_log()
        lines = text.splitlines()
        done = next(i for i, line in enumerate(lines) if line.startswith('RX_OBS kind=1'))
        self.rejects('\n'.join(lines[:done] + lines[done + 1:]) + '\n')
        self.rejects('\n'.join(lines[:done] + [lines[done].replace('kind=1', 'kind=2')] + lines[done:]) + '\n')
        self.rejects(text + 'RX_OBS kind=2 cycle=9999 level=1 write=0 addr=0 wdata=0 rdata=0 err=0 timeout=0 tries=0\n')
        self.rejects(text.replace('RX_OBS kind=4 cycle=9 ', 'RX_OBS kind=4 cycle=99999 ', 1))
        self.rejects(text.replace('RX_OBS kind=4 cycle=9 ', 'RX_OBS kind=x cycle=9 ', 1))

    def test_issued_commands_must_match_the_seed(self):
        text, _ = base_log()
        with self.assertRaises(ValueError):
            M.ledger(text, 'base', 18, 0)
        self.rejects(text.replace('RX_ISSUED n=2 ', 'RX_ISSUED n=3 ', 1))

    def test_directed_response_plan_and_phase_rules_are_enforced(self):
        without_early = [dict(row) for row in M.DIRECTED_ITEMS]
        without_early[14] = dict(stall=2)
        text, _ = synthesize('base', 17, [{}] * 5 + without_early + [dict(stall=1)] * 4 + [{}] * 2)
        self.rejects(text)
        noisy_quiet, _ = synthesize('base', 17, [{}] * 5 + M.DIRECTED_ITEMS + [dict(dup=1)] * 4 + [{}] * 2)
        self.rejects(noisy_quiet)
        shaped_after_delete, _ = synthesize('base', 17, [{}] * 5 + M.DIRECTED_ITEMS + [{}] * 4 + [dict(delay=1)] * 2)
        self.rejects(shaped_after_delete)
        text, _ = base_log()
        self.rejects(text.replace('RX_PHASE name=quiet', 'RX_PHASE name=silent'))

    def test_factory_type_and_error_rule_are_enforced(self):
        text, _ = error_log()
        self.rejects(text.replace('type=rx_err_item', 'type=rx_rsp_item', 1), 'error')
        self.rejects(text, 'base')
        base, _ = base_log()
        self.rejects(base.replace('type=rx_rsp_item', 'type=rx_err_item', 1))

    def test_scoreboard_counters_must_equal_the_ledger(self):
        text, counts = base_log()
        self.rejects(text.replace(f"spurious={counts['spurious']}", f"spurious={counts['spurious'] + 1}"))
        self.rejects(text.replace('RX_COMPLETE', 'RX_FINISHED'))
        self.rejects(text + text.splitlines()[-1] + '\n')

    def native_fixture(self, counts):
        hits = dict(cp_ok=counts['ok'], cp_error_rsp=counts['errors'], cp_retry_ok=counts['retried_ok'], cp_exhausted=counts['exhausted'],
                    cp_timeout=counts['timeouts'], cp_reset_busy=counts['cancelled'], cp_stall=7, cp_boundary=1, cp_early=2, cp_idle_rsp=1)
        data = ''.join(f"C '\x01t\x02user\x01f\x02{M.HERE / 'tb/top.sv'}\x01h\x02TOP.top.{name}\x01o\x02{name}' {n}\n" for name, n in sorted(hits.items()))
        return data, ''.join(f'RX_COVER {name}\n' * n for name, n in hits.items())

    def test_native_covers_are_source_bound_and_equal_to_the_ledger(self):
        text, _ = base_log()
        counts, _ = M.ledger(text, 'base', 17, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'coverage.dat'
            data, log = self.native_fixture(counts)
            path.write_text(data)
            self.assertEqual(M.native(path, log, 'base', counts).keys(), M.COVERS)
            bad = [(data + data, log), (data.replace(str(M.HERE), '/elsewhere'), log), (data, log + 'RX_COVER cp_unknown\n'),
                   (data, log.replace('RX_COVER cp_stall\n', '', 1)), (data.replace("cp_timeout' 1", "cp_timeout' 2"), log + 'RX_COVER cp_timeout\n'),
                   (data.replace("cp_boundary' 1", "cp_boundary' 0"), log.replace('RX_COVER cp_boundary\n', ''))]
            for wrong, output in bad:
                path.write_text(wrong)
                with self.assertRaises(ValueError):
                    M.native(path, output, 'base', counts)
            # The factory test does not need the covers of the injected faults.
            path.write_text(data.replace("cp_boundary' 1", "cp_boundary' 0"))
            relaxed = dict(counts)
            self.assertEqual(len(M.native(path, log.replace('RX_COVER cp_boundary\n', ''), 'error', relaxed)), 10)

    def test_evaluate_requires_the_uvm_summary_and_classifies_mutants(self):
        text, _ = base_log()
        case = dict(test='base', seed=17, commands=0, checks=26, expected_failure=None)
        good = text + UVM + 'RESULT PASS checks=26\n'
        clean = dict(error=None, returncode=0)
        self.assertTrue(M.evaluate(case, clean, good)[0])
        for bad in (good.replace('UVM_ERROR : 0', 'UVM_ERROR : 1'), good.replace('[NO_VISIT_CHECK]', '[OTHER]'), good.replace('2020.3.2', '2020.3.1'),
                    good.replace('checks=26', 'checks=25')):
            self.assertFalse(M.evaluate(case, clean, bad)[0])
        mutant = dict(case, expected_failure='RX_RETRY')
        self.assertTrue(M.evaluate(mutant, dict(error=None, returncode=1), 'CHECK_FAIL RX_RETRY\n')[0])
        self.assertFalse(M.evaluate(mutant, dict(error=None, returncode=1), 'CHECK_FAIL RX_DATA\n')[0])
        self.assertFalse(M.evaluate(mutant, clean, good)[0])

    def test_command_line_rejects_a_missing_library_and_an_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = [sys.executable, str(HERE / 'run.py'), '--verilator', sys.executable, '--iverilog', sys.executable, '--vvp', sys.executable]
            missing = subprocess.run([*run, '--uvm-home', tmp, '--out', str(Path(tmp) / 'out')], capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('prepared UVM', missing.stderr)
            self.assertFalse((Path(tmp) / 'out').exists())
            existing = subprocess.run([*run, '--uvm-home', tmp, '--out', tmp], capture_output=True, text=True)
            self.assertEqual(existing.returncode, 2)


if __name__ == '__main__':
    unittest.main()
