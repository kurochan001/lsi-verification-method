import importlib.util
from pathlib import Path
import re, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-linecode-8b10b')
M = P.M
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('linecode_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
FORMAL = all(shutil.which(tool) for tool in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'z3'))
GOALS = 23
SYMBOLS = [(v, 0) for v in range(256)] + [((y << 5) | x, 1) for x, y in M.CONTROL]
# Columns of a row.
KIND, RST, VALID, K, DATA, EXTRA, X_CODE, X_KERR, X_DATA, X_K, X_CERR, X_DERR, X_ERD, X_DRD, X_WV, X_WORD, X_AL, X_RE = range(18)


def commas(bits):
    return [n for n in range(len(bits) - 6) if M.pack(bits[n:n + 7]) in M.COMMAS]


class CodeTests(unittest.TestCase):
    def test_public_check_values(self):
        """Three codes that are widely printed, as an anchor outside this example's own rules."""
        text = lambda value, control, rd: format(M.encode(value, control, rd)[0], '010b')
        self.assertEqual((text(0xBC, 1, 0), text(0xBC, 1, 1)), ('0011111010', '1100000101'))   # K.28.5
        self.assertEqual((text(0xB5, 0, 0), text(0xB5, 0, 1)), ('1010101010', '1010101010'))   # D.21.5
        self.assertEqual((text(0x4A, 0, 0), text(0x4A, 0, 1)), ('0101010101', '0101010101'))   # D.10.2

    def test_sub_blocks_have_weight_and_complement_structure(self):
        seen = {}
        for x in range(32):
            minus, plus = M.six(x)
            self.assertIn(M.ones(minus), (3, 4), x)
            self.assertTrue(plus == minus or plus == minus ^ 0b111111, x)
            self.assertEqual(plus == minus, M.ones(minus) == 3 and x != 7, x)
            for code in {minus, plus}:
                self.assertNotIn(code, seen, (x, seen.get(code)))
                seen[code] = x
        self.assertEqual(M.six(28, True), (0b001111, 0b110000))
        self.assertFalse({0b001111, 0b110000} & set(seen))
        for y in range(8):
            for rd in (0, 1):
                for x in range(32):
                    code = M.four(y, x, rd)
                    self.assertIn(M.ones(code), (1, 2, 3), (y, rd))
                    self.assertFalse(M.ones(code) == 3 and rd, (y, rd))     # more ones only when the disparity is minus
                    self.assertFalse(M.ones(code) == 1 and not rd, (y, rd))

    def test_codebook_is_decodable_and_every_code_has_weight_four_five_or_six(self):
        self.assertEqual(len(SYMBOLS), 268)
        self.assertEqual(len(M.BOOK), 464)
        for code, entries in M.BOOK.items():
            self.assertEqual(len({(v, k) for v, k, _, _ in entries}), 1, format(code, '010b'))   # one character per code
            weight = M.ones(code)
            self.assertIn(weight, (4, 5, 6))
            for _, _, before, after in entries:   # more ones only from minus, and the disparity then turns over
                self.assertEqual((before, after), {6: (0, 1), 4: (1, 0)}.get(weight, (before, before)))
        self.assertEqual(sum(len(e) == 2 for e in M.BOOK.values()), 72)   # balanced codes used in both disparities

    def test_longest_run_is_five_over_every_pair_of_characters(self):
        longest = 0
        for rd in (0, 1):
            for value, control in SYMBOLS:
                code, after = M.encode(value, control, rd)
                first = M.serial(code)
                for second in SYMBOLS:
                    longest = max(longest, M.runs(first + M.serial(M.encode(second[0], second[1], after)[0])))
        self.assertEqual(longest, 5)

    def test_comma_is_only_in_three_control_characters_and_only_k28_7_makes_a_false_one(self):
        inside, across = set(), set()
        for rd in (0, 1):
            for value, control in SYMBOLS:
                code, after = M.encode(value, control, rd)
                for offset in commas(M.serial(code)):
                    inside.add((offset, value, control))
                for second in SYMBOLS:
                    both = M.serial(code) + M.serial(M.encode(second[0], second[1], after)[0])
                    across |= {(offset, value, control) for offset in commas(both) if offset not in (0, 10)}
        self.assertEqual(inside, {(0, 0x3C, 1), (0, 0xBC, 1), (0, 0xFC, 1)})
        self.assertEqual(across, {(5, 0xFC, 1)})
        self.assertEqual(P.false_comma_follower(), (0x03, 0))

    def test_decoder_model_inverts_the_encoder_and_sorts_all_1024_codes(self):
        for rd in (0, 1):
            for value, control in SYMBOLS:
                code, after = M.encode(value, control, rd)
                self.assertEqual(M.decode(code, rd), (value, control, 0, 0, after))
            sorted_codes = [M.decode(code, rd) for code in range(1024)]
            self.assertEqual((sum(not d[2] and not d[3] for d in sorted_codes), sum(d[3] for d in sorted_codes),
                              sum(d[2] for d in sorted_codes)), (268, 196, 560))
        with self.assertRaises(ValueError):
            M.encode(0x00, 1, 0)

    def test_a_third_of_single_bit_errors_pass_unnoticed_at_first_and_all_of_them_upset_the_disparity(self):
        code_error = disparity_error = unnoticed = 0
        for rd in (0, 1):
            for value, control in SYMBOLS:
                code, after = M.encode(value, control, rd)
                for position in range(10):
                    got = M.decode(code ^ (1 << position), rd)
                    code_error += got[2]
                    disparity_error += got[3]
                    if not got[2] and not got[3]:
                        unnoticed += 1
                        self.assertNotEqual(got[:2], (value, control))
                        self.assertNotEqual(got[4], after)     # the decoder now disagrees with the encoder
        self.assertEqual((code_error, disparity_error, unnoticed), (1848, 1592, 1920))

    def test_aligner_model_finds_the_boundary_again_after_a_lost_bit(self):
        codes = P.stream([(0xBC, 1), (0x12, 0), (0x34, 0), (0xBC, 1), (0x56, 0)])
        a, words = M.Aligner(), []
        bits = M.serial(codes[0]) + M.serial(codes[1]) + M.serial(codes[2])[1:] + M.serial(codes[3]) + M.serial(codes[4])
        for bit in bits:
            valid, word, aligned, realigned = a.step(valid=1, bit=bit)
            if valid:
                words.append((word, realigned))
        self.assertEqual(words[0], (codes[0], 0))
        self.assertEqual(words[1], (codes[1], 0))
        self.assertEqual(words[-2:], [(codes[3], 1), (codes[4], 0)])
        self.assertEqual(a.step(rst_n=0), (0, 0, 0, 0))
        self.assertEqual(a.step(valid=1, bit=1), (0, 0, 0, 0))


class PlanTests(unittest.TestCase):
    def test_fixed_plan_sends_every_character_and_receives_every_code_in_both_disparities(self):
        rows = P.boundary_plan().rows
        sent, raw, rd_enc, rd_dec = set(), set(), 0, 0
        for row in rows:
            if not row[RST]:
                rd_enc = rd_dec = 0
                continue
            if row[KIND] == P.CODEC and row[VALID] and not row[X_KERR]:
                sent.add((rd_enc, row[DATA], row[K]))
            if row[KIND] == P.RAW:
                raw.add((rd_dec, row[EXTRA]))
            rd_enc, rd_dec = row[X_ERD], row[X_DRD]
        self.assertEqual(sent, {(rd, v, k) for rd in (0, 1) for v, k in SYMBOLS})
        self.assertEqual(raw, {(rd, code) for rd in (0, 1) for code in range(1024)})
        illegal = {row[DATA] for row in rows if row[KIND] == P.CODEC and row[VALID] and row[X_KERR]}
        self.assertEqual(len(illegal), 256 - 12)
        flips = {row[EXTRA] for row in rows if row[KIND] == P.CODEC and row[VALID] and M.ones(row[EXTRA]) == 1}
        self.assertEqual(flips, {1 << n for n in range(10)})

    def test_fixed_plan_has_the_alignment_scenes(self):
        rows = [r for r in P.boundary_plan().rows]
        self.assertTrue(any(r[X_RE] for r in rows))                                   # a boundary that moved
        self.assertTrue(any(r[KIND] == P.ALIGN and r[VALID] and not r[DATA] for r in rows))   # alignment disabled
        self.assertTrue(any(r[KIND] == P.ALIGN and not r[VALID] and r[X_AL] for r in rows))   # a cycle without a bit
        words = [r[X_WORD] for r in rows if r[X_WV]]
        self.assertIn(0b0011111000, words)                                            # K.28.7 was sent
        self.assertTrue({w >> 3 for w in words} >= set(M.COMMAS))                     # both polarities aligned

    def test_helpers_find_the_scenes_they_are_named_for(self):
        for (value, control, rd), (second, _) in P.runs_of_five():
            code, after = M.encode(value, control, rd)
            both = M.serial(code) + M.serial(M.encode(second, 0, after)[0])
            self.assertEqual(M.runs(both), 5)
            self.assertLess(M.runs(M.serial(code)), 5)
        self.assertEqual({first[2] for first, _ in P.runs_of_five()}, {0, 1})
        value, mask, follow = P.late_error()
        code, after = M.encode(value, 0, 0)
        got = M.decode(code ^ mask, 0)
        self.assertEqual((got[2], got[3]), (0, 0))
        self.assertNotEqual(got[0], value)                # wrong data, no error yet
        enc_rd, dec_rd, errors = after, got[4], []
        for item in follow:
            code, enc_rd = M.encode(item, 0, enc_rd)
            got = M.decode(code, dec_rd)
            dec_rd = got[4]
            errors.append(got[3])
        self.assertEqual(sum(errors), 1)

    def test_seed_reproduction_and_case_list(self):
        args = SimpleNamespace(profile='nightly', seed=17, iterations=30, demo_bug=0)
        first = P.make_cases(args, {})
        self.assertEqual(first, P.make_cases(args, {}))
        self.assertEqual([c['id'] for c in first], ['boundaries', 'random-seed17', 'random-seed18', 'random-seed19'] +
                         [f'detect-mutation{m}' for m in range(1, 10)])
        self.assertEqual([c['expected_failure'] for c in first[4:]], [P.LABELS[m] for m in range(1, 10)])
        args.seed = 18
        self.assertNotEqual(first[1]['vectors'], P.make_cases(args, {})[1]['vectors'])
        self.assertEqual(first[0]['counts'], dict(characters=839, raw_codes=2821, words=36))

    def test_random_plan_mixes_the_three_kinds_of_rows_with_errors_idle_cycles_and_slips(self):
        rows = P.random_plan(17, 400).rows
        self.assertEqual({r[KIND] for r in rows}, {P.CODEC, P.ALIGN, P.RAW})
        self.assertTrue(any(r[KIND] == P.CODEC and r[VALID] and r[EXTRA] for r in rows))
        self.assertTrue(any(r[KIND] == P.CODEC and r[RST] and not r[VALID] for r in rows))
        self.assertTrue(any(r[X_KERR] for r in rows))
        self.assertTrue(any(r[X_RE] for r in rows))
        self.assertTrue(any(r[X_CERR] for r in rows) and any(r[X_DERR] for r in rows))


@unittest.skipUnless(ICARUS, 'Icarus required')
class RtlTests(unittest.TestCase):
    def test_real_rtl_every_goal_from_the_fixed_plan_and_every_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-linecode-8b10b', out, '--iterations', '40')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['success'], summary['complete'], summary['planned']), (True, True, 11))
            self.assertEqual((summary['mutations_detected'], summary['functional_pass']), (9, 2))
            coverage = read_json(out / 'coverage.json')['codec']
            self.assertEqual((coverage['hit'], coverage['missing']), (GOALS, []))
            self.assertTrue(all('codec-boundaries' in cases for cases in coverage['hits'].values()))   # not left to random rows
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('12', '0', '0'))
            for mutation in range(1, 10):
                record = read_json(out / f'codec-detect-mutation{mutation}/result.json')
                self.assertEqual((record['status'], record['credited_coverage']), ('detected', []))
                self.assertIn(P.LABELS[mutation], record['message'])
            self.assertTrue((out / 'codec-boundaries/wave.vcd').exists())

    def test_demo_faults_fail_the_fixed_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in (2, 7, 9):
                out = Path(tmp) / f'p{fault}'
                result = run_example('local-linecode-8b10b', out, '--iterations', '2', '--demo-bug', str(fault))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(read_json(out / 'codec-boundaries/result.json')['status'], 'fail')

    def test_a_wrong_expected_value_in_each_column_is_reported_under_its_own_label(self):
        p = P.Plan()
        p.reset(2)
        p.send(0x4A)
        p.send(0xBC, 1)
        p.send(0x00, 1)
        p.raw(0b1111110000)
        for code in P.stream([(0xBC, 1), (0x4A, 0)]):
            p.word(code)
        rows = p.rows
        self.assertIn(f'RESULT PASS checks={len(rows)}', simulate_vectors(P, rows).stdout)
        word_row = next(n for n, r in enumerate(rows) if r[X_WV])
        for index, column, label in ((2, X_CODE, 'LC_CODE'), (2, X_DATA, 'LC_DATA'), (2, X_CERR, 'LC_CODE_ERR'),
                                     (2, X_DERR, 'LC_DISP_ERR'), (3, X_ERD, 'LC_ENC_RD'), (3, X_DRD, 'LC_DEC_RD'),
                                     (4, X_KERR, 'LC_K_ERR'), (5, X_CERR, 'LC_CODE_ERR'), (word_row, X_WORD, 'LC_WORD'),
                                     (word_row, X_AL, 'LC_ALIGN'), (word_row + 1, X_WV, 'LC_WORD')):
            wrong = [list(r) for r in rows]
            wrong[index][column] ^= 1
            output = simulate_vectors(P, wrong).stdout
            self.assertIn('CHECK_FAIL ' + label, output, (index, column))
            self.assertNotIn('RESULT PASS', output)

    def test_run_and_disparity_monitors_do_not_depend_on_the_model(self):
        """The expected code is set to what a damaged encoder sends: only the two monitors can object."""
        p = P.Plan()
        p.reset(2)
        p.send(0x20)                       # D.0.1 turns the disparity to plus
        p.send(0x23)                       # D.3.1
        rows = [list(r) for r in p.rows]
        heavy = {'enc_8b10b_comb.sv': [("5'd3:  six_table = {1'b0, 6'b110001};", "5'd3:  six_table = {1'b0, 6'b110101};")]}
        rows[3][X_CODE] = 0b1101011001     # six ones while the disparity is plus
        self.assertIn('CHECK_FAIL LC_DISPARITY', simulate_vectors(P, rows, None, heavy).stdout)
        rows = [list(r) for r in p.rows]
        long_run = {'enc_8b10b_comb.sv': [("5'd0:  six_table = {1'b1, 6'b100111};", "5'd0:  six_table = {1'b0, 6'b111111};")]}
        rows[2][X_CODE] = 0b1111111001
        self.assertIn('CHECK_FAIL LC_RUN', simulate_vectors(P, rows, None, long_run).stdout)
        self.assertIn('RESULT PASS', simulate_vectors(P, p.rows).stdout)

    def test_an_unknown_output_fails(self):
        p = P.Plan()
        p.reset(2)
        p.send(0x4A)
        edits = {'dec_8b10b_comb.sv': [("assign k = accepted && (k28 || chosen[3]);", "assign k = 1'bx;")]}
        self.assertIn('CHECK_FAIL LC_DATA', simulate_vectors(P, p.rows, None, edits).stdout)


class FormalPlanTests(unittest.TestCase):
    def test_plan_has_the_proof_the_covers_one_task_per_codec_mutant_and_the_forward_only_misses(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['codec-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 8)] + [f'forward-misses-mutation{m}' for m in (5, 6, 7)])
        self.assertEqual(plan[0]['parameters'], dict(MUTATION=0, SIDE=F.ALL))
        self.assertEqual({c['parameters']['SIDE'] for c in plan[2:6]}, {F.FORWARD_ONLY})
        self.assertEqual([c['parameters']['SIDE'] for c in plan[6:9]], [F.BACKWARD_ONLY, F.OTHER_ONLY, F.BACKWARD_ONLY])
        self.assertEqual(F.properties({}, plan[7])['assert'], {'ap_other'})
        for case in plan[9:]:
            self.assertEqual((case['mode'], case['expect'], case['category'], case['parameters']['SIDE']),
                             ('prove', 'PASS', 'diagnostic', F.FORWARD_ONLY))
        for case in plan:
            if case['failure']:
                self.assertIn(case['failure'], F.properties({}, case)['assert'])
        self.assertEqual(F.properties({}, plan[0])['assert'], F.FORWARD | F.BACKWARD)
        self.assertEqual(F.properties({}, plan[9])['cover'], F.FORWARD_COVERS)
        self.assertEqual(F.plan(F.BOUND, 2)[0]['parameters']['MUTATION'], 2)
        self.assertEqual(F.MUTANTS, 7)      # mutants 8 and 9 change the aligner, which the proof does not contain

    def test_property_names_match_the_harness(self):
        text = (HERE / 'linecode_formal.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.FORWARD | F.BACKWARD | F.FORWARD_COVERS | F.BACKWARD_COVERS | {'as_initial_reset'})
        self.assertEqual(text.count('assume('), 1)

    @unittest.skipUnless(FORMAL, 'formal tools required')
    def test_proof_completes_and_a_mutant_of_each_side_is_refuted(self):
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('codec-proof', 'pass'), ('detect-mutation2', 'detected'), ('detect-mutation5', 'detected')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--task', task, '--out', str(out)],
                                        capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'codec-{task}/result.json')['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()
