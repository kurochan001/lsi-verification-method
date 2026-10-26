"""Run the actual ARB, including negative cases and per-configuration gates."""

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
SPEC = importlib.util.spec_from_file_location("arbiter_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArbiterRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("iverilog") or not shutil.which("vvp"):
            raise RuntimeError("Install Icarus Verilog before running these tests")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arbiter-runner-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.index = 0

    def invoke(self, *options):
        self.index += 1
        out = self.directory / f"results{self.index}"
        proc = subprocess.run([sys.executable, str(RUNNER), "--out", str(out), *options],
                              capture_output=True, text=True, timeout=90)
        self.assertTrue((out / "junit.xml").exists(), proc.stdout + proc.stderr)
        return proc, out, json.loads((out / "summary.json").read_text()), ET.parse(out / "junit.xml").getroot()

    def fake_tool(self, body):
        path = self.directory / "fake-vvp"
        path.write_text(f"#!{sys.executable}\nimport sys, time, subprocess\n"
                        "if '-V' in sys.argv:\n    print('fake-vvp for runner test')\n    sys.exit(0)\n" + body)
        path.chmod(0o755)
        return str(path)

    def test_three_configurations_pass_independent_gates(self):
        ids = set()
        for ports, goals in ((2, 21), (3, 31), (4, 49)):
            proc, out, summary, junit = self.invoke("--ports", str(ports))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(summary["functional_pass"], 2)
            self.assertEqual(summary["mutations_detected"], 3)
            self.assertEqual(summary["diagnostics_pass"], 1)
            self.assertEqual(summary["coverage_hit"], goals)
            self.assertEqual(len(junit.findall("testcase")), 7)
            self.assertEqual(junit.attrib["failures"], "0")
            self.assertEqual(junit.attrib["errors"], "0")
            for case in junit.findall("testcase"):
                key = (case.attrib["classname"], case.attrib["name"])
                self.assertNotIn(key, ids)
                ids.add(key)
            manifest = json.loads((out / "manifest.json").read_text())
            for planned in manifest["cases"]:
                wave = out / planned["id"] / "wave.vcd"
                self.assertTrue(wave.is_file(), f"missing waveform for {planned['id']}")
                self.assertIn("$enddefinitions $end", wave.read_text())
            diagnostic = json.loads((out / f"p{ports}-blocked-sink/result.json").read_text())
            self.assertEqual(diagnostic["metrics"]["opportunities"], 0)
            self.assertGreater(diagnostic["metrics"]["max_wall"], ports)
            self.assertEqual(diagnostic["credited_coverage"], [])
            coverage = json.loads((out / "coverage.json").read_text())
            for contributors in coverage["hits"].values():
                self.assertTrue(all("mutation" not in c and "blocked" not in c for c in contributors))
            for name in (f"p{ports}-boundaries", f"p{ports}-random-seed17"):
                metrics = json.loads((out / name / "result.json").read_text())["metrics"]
                self.assertEqual(metrics["opportunities"], metrics["accepted"])
                self.assertEqual(sum(p["count"] for p in metrics["per_port"]), metrics["accepted"])
                self.assertLessEqual(metrics["max_service_wait"], ports)

    def test_nightly_records_reproducible_seed_vectors(self):
        proc, out, summary, junit = self.invoke("--profile", "nightly", "--seed", "73", "--cycles", "40")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(summary["functional_pass"], 4)
        self.assertEqual(len(junit.findall("testcase")), 9)
        manifest = json.loads((out / "manifest.json").read_text())
        random_cases = [c for c in manifest["cases"] if "seed" in c]
        self.assertEqual([c["seed"] for c in random_cases], [73, 74, 75])
        for case in random_cases:
            self.assertEqual(case["vectors"], MODULE.random_vectors(3, case["seed"], 40))
            rows = (out / case["id"] / "vectors.txt").read_text().splitlines()
            observed = [[int(r), int(mask, 16), int(ready)] for line in rows
                        for r, mask, ready in [line.split()]]
            self.assertEqual(observed, case["vectors"])

    def test_each_demo_bug_fails_normal_cases_and_junit(self):
        for mutation, label in ((1, "ARB_ONEHOT"), (2, "ARB_STABILITY"), (3, "ARB_ORDER")):
            with self.subTest(mutation=mutation):
                proc, out, summary, junit = self.invoke("--demo-bug", str(mutation))
                self.assertEqual(proc.returncode, 1)
                self.assertFalse(summary["success"])
                self.assertEqual(summary["mutations_detected"], 3)
                self.assertGreater(len(junit.findall("testcase/failure")), 0)
                self.assertIn(f"CHECK_FAIL {label}", (out / "p3-boundaries/simulation.log").read_text())

    def test_build_error_is_not_a_detected_mutation(self):
        proc, _, summary, junit = self.invoke("--iverilog", str(self.directory / "missing"))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["mutations_detected"], 0)
        self.assertEqual(len(junit.findall("testcase/error")), 6)

    def test_timeout_is_not_a_detected_mutation(self):
        tool = self.fake_tool("time.sleep(2)\n")
        proc, _, summary, junit = self.invoke("--vvp", tool, "--timeout", "0.05")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["mutations_detected"], 0)
        self.assertEqual(len(junit.findall("testcase/error")), 6)

    def test_unrelated_crash_does_not_count_as_detection(self):
        tool = self.fake_tool("print('CHECK_FAIL ARB_UNRELATED')\nsys.exit(1)\n")
        proc, _, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["mutations_detected"], 0)
        self.assertEqual(len(junit.findall("testcase/error")), 3)

    def test_unmet_requirement_fails_otherwise_passing_cases(self):
        catalog = json.loads((RUNNER.parent / "requirements.json").read_text())
        catalog["requirements"].append(dict(id="UNREACHED", kind="fixed", goals=["never"]))
        path = self.directory / "requirements.json"
        path.write_text(json.dumps(catalog))
        proc, _, summary, junit = self.invoke("--requirements", str(path))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["functional_pass"], 2)
        self.assertEqual(len(junit.findall("testcase/failure")), 1)

    def test_coverage_is_not_inferred_or_supplied_by_mutants(self):
        tool = self.fake_tool(
            f"p = subprocess.run([{shutil.which('vvp')!r}, *sys.argv[1:]], capture_output=True, text=True)\n"
            "normal = any(arg.endswith('arbiter-0.vvp') for arg in sys.argv)\n"
            "print('\\n'.join(line for line in p.stdout.splitlines() if not (normal and line.startswith('COVER '))))\n"
            "sys.exit(p.returncode)\n")
        proc, out, summary, _ = self.invoke("--vvp", tool)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["coverage_hit"], 0)
        self.assertEqual(summary["mutations_detected"], 3)
        self.assertFalse(json.loads((out / "coverage.json").read_text())["hits"])

    def test_zero_exit_without_completion_is_error(self):
        tool = self.fake_tool("print('exited early')\n")
        proc, _, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["mutations_detected"], 0)
        self.assertEqual(len(junit.findall("testcase/error")), 6)

    def simulate_fixture(self, vectors, mutation=0, order_check=1):
        path = self.directory / "fixture.txt"
        path.write_text("".join(f"{rst} {mask:x} {ready}\n" for rst, mask, ready in vectors))
        image = self.directory / "fixture.vvp"
        build = subprocess.run(["iverilog", "-g2012", "-s", "arbiter_tb", "-Parbiter_tb.PORTS=3",
                                f"-Parbiter_tb.MUTATION={mutation}", f"-Parbiter_tb.CHECK_ORDER={order_check}",
                                "-o", str(image), str(RUNNER.parent / "rtl/rr_arbiter.sv"),
                                str(RUNNER.parent / "tb/arbiter_tb.sv")], capture_output=True, text=True, timeout=10)
        self.assertEqual(build.returncode, 0, build.stderr)
        return subprocess.run(["vvp", str(image), f"+VECTORS={path}"],
                              capture_output=True, text=True, timeout=10)

    def test_fairness_monitor_detects_starvation_without_order_checker(self):
        result = self.simulate_fixture([[0, 0, 0]] + [[1, 7, 1] for _ in range(5)], mutation=3, order_check=0)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CHECK_FAIL ARB_FAIRNESS", result.stdout)

    def test_unaccepted_requests_cannot_be_withdrawn(self):
        result = self.simulate_fixture([[0, 0, 0], [1, 1, 0], [1, 0, 0]])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CHECK_FAIL ARB_SOURCE_HOLD", result.stdout)

    def test_missing_service_metrics_do_not_count_as_completion(self):
        tool = self.fake_tool(
            f"p = subprocess.run([{shutil.which('vvp')!r}, *sys.argv[1:]], capture_output=True, text=True)\n"
            "print('\\n'.join(line for line in p.stdout.splitlines() if not line.startswith(('METRICS ', 'SERVICE '))))\n"
            "sys.exit(p.returncode)\n")
        proc, _, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary["functional_pass"], 0)
        self.assertEqual(summary["diagnostics_pass"], 0)
        self.assertEqual(summary["mutations_detected"], 3)
        self.assertEqual(len(junit.findall("testcase/error")), 3)

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
