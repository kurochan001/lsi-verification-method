"""Check native coverage auditing and failure classification without EDA tools."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

RUNNER = Path(__file__).resolve().parents[1] / "run.py"
SPEC = importlib.util.spec_from_file_location("sva_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SvaRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sva-runner-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        _, self.labels = MODULE.load_catalog(RUNNER.parent / "requirements.json")
        self.args = argparse.Namespace(profile="smoke", seed=17, cycles=40, demo_bug=0)

    def native_record(self, label, value=1, source=None, hierarchy=None):
        source = source or RUNNER.parent / "irq_checker.sv"
        hierarchy = hierarchy or f"TOP.sva_tb.checker_inst.{label}"
        return f"C '\x01f\x02{source}\x01t\x02user\x01o\x02{label}\x01h\x02{hierarchy}' {value}\n"

    def execution(self, code=0, error=None):
        return dict(returncode=code, error=error)

    def output(self, case, counts):
        return ("".join(f"COVER {label}\n" * value for label, value in counts.items()) +
                f"RESULT PASS checks={case['checks']}\n")

    def test_smoke_and_nightly_plans_close_one_cycle_obligations(self):
        for profile, size in (("smoke", 9), ("nightly", 11)):
            self.args.profile = profile
            plan = MODULE.make_plan(self.args)
            self.assertEqual(len(plan), size)
            self.assertEqual(len({c["id"] for c in plan}), size)
            self.assertEqual(sum(c["expected_failure"] is not None for c in plan), 6)
            for case in plan:
                self.assertEqual(case["checks"], len(case["vectors"]))
                tail = case["vectors"][-1]
                self.assertEqual((tail[0], tail[1], tail[2], tail[4]), (1, 0, 0, 0))

    def test_random_seed_is_reproducible_and_has_reset_and_tail(self):
        a = MODULE.random_vectors(73, 200)
        self.assertEqual(a, MODULE.random_vectors(73, 200))
        self.assertNotEqual(a, MODULE.random_vectors(74, 200))
        self.assertEqual(len(a), 202)
        self.assertEqual(a[0], [0, 0, 0, 0, 0])
        self.assertEqual(a[-1], [1, 0, 0, 0, 0])

    def test_native_user_counters_are_read_from_exact_checker(self):
        path = self.directory / "coverage.dat"
        modern = "# SystemC::Coverage-3\n" + "".join(self.native_record(c, 2) for c in self.labels)
        legacy = modern.replace("\x01t\x02user", "\x01page\x02v_user/irq_checker")
        for content in (modern, legacy):
            path.write_text(content)
            self.assertEqual(MODULE.native_counts(path, self.labels), {c: 2 for c in self.labels})

    def test_missing_duplicate_or_foreign_native_counters_are_rejected(self):
        rows = [self.native_record(c) for c in sorted(self.labels)]
        label = sorted(self.labels)[0]
        for content in ("".join(rows[1:]), "".join(rows + [rows[0]]),
                        self.native_record(label, source="/wrong.sv") + "".join(rows[1:]),
                        self.native_record(label, hierarchy="TOP.wrong") + "".join(rows[1:]),
                        "malformed\n" + "".join(rows)):
            with self.subTest(content=content[:80]):
                path = self.directory / "coverage.dat"
                path.write_text(content)
                with self.assertRaises(ValueError):
                    MODULE.native_counts(path, self.labels)

    def test_expected_assertion_without_native_evidence_is_error(self):
        case = next(c for c in MODULE.make_plan(self.args) if c["expected_failure"])
        status, _ = MODULE.classify(case, self.execution(1),
                                    f"CHECK_FAIL {case['expected_failure']}\n", None)
        self.assertEqual(status, "error")

    def test_cover_log_and_native_counter_disagreement_is_error(self):
        case = MODULE.make_plan(self.args)[0]
        status, _ = MODULE.classify(case, self.execution(), f"RESULT PASS checks={case['checks']}\n",
                                    {c: 1 for c in self.labels})
        self.assertEqual(status, "error")

    def test_unrelated_crash_and_timeout_are_not_detection(self):
        case = next(c for c in MODULE.make_plan(self.args) if c["expected_failure"])
        for execution, output in ((self.execution(1), "CHECK_FAIL UNRELATED\n"),
                                  (self.execution(None, "timeout"), f"CHECK_FAIL {case['expected_failure']}\n")):
            status, _ = MODULE.classify(case, execution, output, {c: 0 for c in self.labels})
            self.assertEqual(status, "error")

    def test_vacuous_case_identifies_absent_antecedents(self):
        case = MODULE.make_plan(self.args)[-1]
        counts = {c: int(c in {"cp_hold_seen", "cp_hold_done"}) for c in self.labels}
        status, _ = MODULE.classify(case, self.execution(), self.output(case, counts), counts)
        self.assertEqual(status, "pass")
        counts = {c: 1 for c in self.labels}
        status, _ = MODULE.classify(case, self.execution(), self.output(case, counts), counts)
        self.assertEqual(status, "error")

    def test_duplicate_requirement_or_cover_is_rejected(self):
        original = json.loads((RUNNER.parent / "requirements.json").read_text())
        for field in ("id", "goals"):
            catalog = json.loads(json.dumps(original))
            catalog["requirements"][1][field] = catalog["requirements"][0][field]
            path = self.directory / "requirements.json"
            path.write_text(json.dumps(catalog))
            with self.assertRaises(ValueError):
                MODULE.load_catalog(path)

    def test_assertion_inventory_and_cover_bindings_are_checked(self):
        original = json.loads((RUNNER.parent / "requirements.json").read_text())
        for corruption in ("unknown", "duplicate", "wrong-covers", "missing"):
            catalog = json.loads(json.dumps(original))
            requirements = catalog["requirements"]
            if corruption == "unknown":
                requirements[0]["assertion"] = "ap_not_implemented"
            elif corruption == "duplicate":
                requirements[1]["assertion"] = requirements[0]["assertion"]
            elif corruption == "wrong-covers":
                requirements[0]["goals"], requirements[1]["goals"] = requirements[1]["goals"], requirements[0]["goals"]
            else:
                requirements.pop()
            with self.subTest(corruption=corruption):
                path = self.directory / "requirements.json"
                path.write_text(json.dumps(catalog))
                with self.assertRaises(ValueError):
                    MODULE.load_catalog(path)

    def test_existing_output_is_not_overwritten(self):
        out = self.directory / "existing"
        out.mkdir()
        sentinel = out / "keep.txt"
        sentinel.write_text("old evidence")
        result = subprocess.run([sys.executable, str(RUNNER), "--out", str(out)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), "old evidence")

    def test_missing_compiler_emits_errors_for_all_planned_cases(self):
        out = self.directory / "missing-tool"
        result = subprocess.run([sys.executable, str(RUNNER), "--out", str(out),
                                 "--verilator", str(self.directory / "missing-verilator")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary["sensitivity_detected"], 0)
        self.assertFalse(summary["success"])
        junit = ET.parse(out / "junit.xml").getroot()
        self.assertEqual(len(junit.findall("testcase")), 10)
        self.assertEqual(len(junit.findall("testcase/error")), 9)


if __name__ == "__main__":
    unittest.main()
