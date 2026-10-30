"""Exercise selection, fresh RTL validation, lost sensitivity and failure paths."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

RUNNER = Path(__file__).resolve().parents[1] / "run.py"
SPEC = importlib.util.spec_from_file_location("reduction_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reduction-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def invoke(self, *options):
        out = self.directory / "results"
        result = subprocess.run([sys.executable, str(RUNNER), "--out", str(out), *options],
                                capture_output=True, text=True, timeout=90)
        self.assertTrue((out / "junit.xml").exists(), result.stdout + result.stderr)
        return result, out, json.loads((out / "summary.json").read_text()), ET.parse(out / "junit.xml").getroot()

    def require_tools(self):
        self.assertTrue(shutil.which("iverilog") and shutil.which("vvp"), "Install Icarus Verilog")

    def test_greedy_uses_goals_per_cycle_and_is_deterministic(self):
        observations = [dict(id="a", checks=1, observed_coverage=["x"], status="pass"),
                        dict(id="b", checks=3, observed_coverage=["x", "y"], status="pass"),
                        dict(id="c", checks=2, observed_coverage=["x", "y"], status="pass")]
        selected, decisions = MODULE.greedy_select(observations, {"x", "y"})
        self.assertEqual(selected, ["c"])
        self.assertEqual(decisions[0]["added_goals"], ["x", "y"])
        self.assertEqual((selected, decisions), MODULE.greedy_select(list(reversed(observations)), {"x", "y"}))

    def test_mandatory_stress_is_retained_without_new_required_goals(self):
        observations = [dict(id="short", checks=2, observed_coverage=["x"], status="pass"),
                        dict(id="stress", checks=20, observed_coverage=["optional"], status="pass")]
        selected, _ = MODULE.greedy_select(observations, {"x"}, ["stress"])
        self.assertEqual(selected, ["short", "stress"])

    def test_invalid_or_incomplete_learning_is_rejected(self):
        base = dict(id="a", checks=2, observed_coverage=["x"], status="pass")
        for rows in ([dict(base, status="fail")], [dict(base, checks=0)], [base, base], [base]):
            with self.assertRaises(ValueError):
                MODULE.greedy_select(rows, {"x", "missing"})

    def test_suite_profiles_are_reproducible_and_short_bursts_are_bounded(self):
        for profile, count in (("smoke", 24), ("nightly", 26)):
            cases = MODULE.make_candidates(profile, 17)
            self.assertEqual(cases, MODULE.make_candidates(profile, 17))
            self.assertEqual(len(cases), count)
            for case in cases:
                self.assertEqual(case["checks"], len(case["vectors"]))
                if case["id"].startswith("short-random"):
                    streak = 0
                    for rst, event, _, _ in case["vectors"]:
                        streak = streak + 1 if rst and event else 0
                        self.assertLessEqual(streak, 4)

    def test_catalog_rejects_duplicate_candidates_and_missing_guards(self):
        cases = MODULE.make_candidates("smoke", 17)
        with self.assertRaises(ValueError):
            MODULE.load_catalog(RUNNER.parent / "requirements.json", cases + [cases[0]])
        catalog = json.loads((RUNNER.parent / "requirements.json").read_text())
        catalog["guard_cases"] = ["absent"]
        path = self.directory / "catalog.json"
        path.write_text(json.dumps(catalog))
        with self.assertRaises(ValueError):
            MODULE.load_catalog(path, cases)

    def test_unrelated_failure_timeout_or_missing_completion_is_not_detection(self):
        case = dict(checks=2)
        for code, error, output in ((1, None, "CHECK_FAIL OTHER\n"),
                                     (None, "timeout", "CHECK_FAIL IRQ_RESET\n"),
                                     (0, None, "early exit\n"),
                                     (1, None, "CHECK_FAIL IRQ_RESET\nRESULT PASS checks=2\n")):
            execution = dict(returncode=code, error=error)
            status, _ = MODULE.classify_probe(case, execution, output, ("IRQ_RESET",))
            self.assertEqual(status, "error")

    def test_real_comparison_preserves_goals_but_exposes_lost_history_detection(self):
        self.require_tools()
        proc, out, summary, junit = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(summary["success"])
        self.assertEqual(len(junit.findall("testcase")), 18)
        self.assertEqual(junit.attrib["failures"], "0")
        self.assertEqual(junit.attrib["errors"], "0")
        metrics = summary["measurements"]
        for strategy in MODULE.STRATEGIES:
            self.assertEqual(metrics[strategy]["coverage_hit"], 19)
            self.assertTrue(all(metrics[strategy]["probes"][str(m)]["detected"] for m in (1, 2, 3)))
        self.assertTrue(metrics["full"]["probes"]["4"]["detected"])
        self.assertFalse(metrics["coverage_only"]["probes"]["4"]["detected"])
        self.assertTrue(metrics["guarded"]["probes"]["4"]["detected"])
        for strategy in ("coverage_only", "guarded"):
            self.assertLess(metrics[strategy]["cycles"], metrics["full"]["cycles"])
        runs = json.loads((out / "runs.json").read_text())
        # Every strategy has its own new normal runs, independent of learning.
        for strategy in MODULE.STRATEGIES:
            normal = [r for r in runs if r["phase"] == f"{strategy}/normal"]
            self.assertEqual(len(normal), metrics[strategy]["cases"])
            self.assertTrue(all(r["status"] == "pass" for r in normal))
            self.assertEqual(sum(r["executed_cycles"] for r in normal), metrics[strategy]["cycles"])

    def test_dropping_mandatory_stress_fails_even_with_all_required_goals(self):
        self.require_tools()
        proc, _, summary, _ = self.invoke("--omit-guard")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(summary["success"])
        self.assertEqual(summary["measurements"]["guarded"]["coverage_hit"], 19)
        self.assertEqual(summary["gates"]["selection"]["status"], "fail")
        self.assertEqual(summary["gates"]["guarded/mutation4"]["status"], "fail")

    def test_failed_learning_cannot_be_hidden_by_selection(self):
        self.require_tools()
        proc, out, summary, _ = self.invoke("--demo-bug", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(summary["success"])
        self.assertFalse((out / "selection.json").exists())
        self.assertEqual(summary["simulations"], summary["candidate_cases"])

    def test_missing_compiler_is_never_a_detected_mutation(self):
        proc, out, summary, _ = self.invoke("--iverilog", str(self.directory / "missing"))
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(summary["success"])
        runs = json.loads((out / "runs.json").read_text())
        self.assertTrue(all(r["status"] == "error" for r in runs))
        self.assertFalse((out / "selection.json").exists())

    def test_existing_output_is_not_overwritten(self):
        out = self.directory / "existing"
        out.mkdir()
        sentinel = out / "keep.txt"
        sentinel.write_text("old evidence")
        proc = subprocess.run([sys.executable, str(RUNNER), "--out", str(out)], capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(sentinel.read_text(), "old evidence")


if __name__ == "__main__":
    unittest.main()
