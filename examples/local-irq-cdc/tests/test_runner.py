"""Exercise the CLI, real simulator, error classification, and JUnit gate."""

import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import signal
import tempfile
import time
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


RUNNER = Path(__file__).resolve().parents[1] / "run.py"
SPEC = importlib.util.spec_from_file_location("irq_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RunnerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("iverilog") or not shutil.which("vvp"):
            raise RuntimeError("Install Icarus Verilog before running these tests")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="irq-runner-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def invoke(self, *options):
        output = self.directory / "results"
        process = subprocess.run([sys.executable, str(RUNNER), "--out", str(output), *options],
                                 capture_output=True, text=True, timeout=90)
        self.assertTrue((output / "junit.xml").is_file(), process.stdout + process.stderr)
        summary = json.loads((output / "summary.json").read_text())
        junit = ET.parse(output / "junit.xml").getroot()
        manifest = json.loads((output / "manifest.json").read_text())
        ids = [node.attrib["name"] for node in junit.findall("testcase")
               if node.attrib["classname"] != "irq.gate"]
        self.assertIsNotNone(junit.find("testcase[@name='requirements-and-coverage']"))
        self.assertEqual(ids, [case["id"] for case in manifest["cases"]])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(summary["planned"], len(ids))
        self.assertTrue(summary["complete"])
        return process, summary, junit

    def fake_tool(self, body):
        tool = self.directory / "fake-vvp"
        tool.write_text(f"#!{sys.executable}\nimport sys, time\n"
                        "if '-V' in sys.argv:\n    print('fake-vvp for runner tests')\n    sys.exit(0)\n" + body)
        tool.chmod(0o755)
        return str(tool)

    def test_normal_and_expected_mutations(self):
        process, summary, junit = self.invoke()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(summary["functional"]["pass"], 32)
        self.assertEqual(summary["mutations"]["detected"], 4)
        self.assertEqual(summary["checker_selftests"]["detected"], 1)
        coverage = json.loads((self.directory / "results/coverage.json").read_text())
        self.assertEqual(coverage["hit"], 50)
        self.assertEqual(len(coverage["requirements"]), 8)
        self.assertTrue(all(r["passed"] for r in coverage["requirements"]))
        self.assertEqual(len([goal for goal in coverage["hits"] if goal.startswith("cdc/")]), 18)
        self.assertEqual(junit.attrib["failures"], "0")
        self.assertEqual(junit.attrib["errors"], "0")
        self.assertEqual(len(junit.findall("testcase")), 38)

    def test_nightly_adds_recorded_random_sequences(self):
        process, summary, _ = self.invoke("--profile", "nightly", "--seed", "73")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(summary["functional"]["pass"], 35)
        manifest = json.loads((self.directory / "results/manifest.json").read_text())
        random_cases = [case for case in manifest["cases"] if case["mode"] == "random"]
        self.assertEqual([case["seed"] for case in random_cases], [73, 74, 75])
        for case in random_cases:
            vector_file = self.directory / "results" / case["id"] / "vectors.txt"
            observed = [list(map(int, line.split())) for line in vector_file.read_text().splitlines()]
            self.assertEqual(observed, case["vectors"])
            self.assertEqual(len(observed), 64)

    def test_real_bug_fails_job_and_junit(self):
        process, summary, junit = self.invoke("--demo-bug", "1")
        self.assertEqual(process.returncode, 1)
        self.assertFalse(summary["success"])
        self.assertEqual(summary["functional"]["fail"], 8)
        self.assertEqual(len(junit.findall("testcase/failure")), 9)
        self.assertEqual(summary["mutations"]["detected"], 4)

    def test_missing_compiler_is_error_not_detected_mutation(self):
        process, summary, junit = self.invoke("--iverilog", str(self.directory / "missing-compiler"))
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(junit.findall("testcase/error")), 37)
        self.assertEqual(summary["mutations"]["detected"], 0)

    def test_timeout_is_error_not_detected_mutation(self):
        tool = self.fake_tool("time.sleep(2)\n")
        process, summary, junit = self.invoke("--vvp", tool, "--timeout", "0.05")
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(junit.findall("testcase/error")), 37)
        self.assertEqual(summary["mutations"]["detected"], 0)

    def test_zero_exit_without_completion_is_error(self):
        tool = self.fake_tool("print('simulation stopped without a completion record')\n")
        process, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(junit.findall("testcase/error")), 37)
        self.assertEqual(summary["mutations"]["detected"], 0)

    def test_unrelated_failure_does_not_kill_expected_mutations(self):
        tool = self.fake_tool("print('CHECK_FAIL IRQ_UNRELATED')\nsys.exit(1)\n")
        process, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(summary["mutations"]["error"], 4)
        self.assertEqual(summary["mutations"]["detected"], 0)
        self.assertEqual(len(junit.findall("testcase/error")), 5)

    def test_unmet_requirement_fails_otherwise_green_regression(self):
        catalog = json.loads((RUNNER.parent / "requirements.json").read_text())
        catalog["requirements"][0]["goals"].append("atomic/p0/en0/op99")
        path = self.directory / "requirements.json"
        path.write_text(json.dumps(catalog))
        process, summary, junit = self.invoke("--requirements", str(path))
        self.assertEqual(process.returncode, 1)
        self.assertEqual(summary["functional"]["pass"], 32)
        self.assertEqual(len(junit.findall("testcase/failure")), 1)
        self.assertIsNotNone(junit.find("testcase[@name='requirements-and-coverage']/failure"))

    def test_missing_coverage_is_not_inferred_from_planned_case(self):
        real_vvp = shutil.which("vvp")
        tool = self.fake_tool("import subprocess\n" +
                              f"p = subprocess.run([{real_vvp!r}, *sys.argv[1:]], capture_output=True, text=True)\n" +
                              "print('\\n'.join(line for line in p.stdout.splitlines() if not line.startswith('COVER ')))\n" +
                              "sys.exit(p.returncode)\n")
        process, summary, _ = self.invoke("--vvp", tool)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(summary["coverage_hit"], 0)
        self.assertEqual(summary["functional"]["error"], 32)

    def test_mutants_cannot_fill_missing_functional_coverage(self):
        real_vvp = shutil.which("vvp")
        tool = self.fake_tool("import subprocess\n" +
                              f"p = subprocess.run([{real_vvp!r}, *sys.argv[1:]], capture_output=True, text=True)\n" +
                              "lines = p.stdout.splitlines()\n" +
                              "if any(arg.endswith('irq-0.vvp') for arg in sys.argv) and '+MODE=cdc' in sys.argv:\n" +
                              "    lines = [line for line in lines if not line.startswith('COVER cdc/')]\n" +
                              "print('\\n'.join(lines))\nsys.exit(p.returncode)\n")
        process, summary, _ = self.invoke("--vvp", tool)
        self.assertEqual(process.returncode, 1)
        coverage = json.loads((self.directory / "results/coverage.json").read_text())
        self.assertFalse(any(goal.startswith("cdc/") for goal in coverage["hits"]))
        self.assertEqual(summary["coverage_hit"], 32)
        mutant = json.loads((self.directory / "results/detect-cdc-early-receiver/result.json").read_text())
        self.assertEqual(mutant["credited_coverage"], [])

    def child_wrapper(self):
        marker = self.directory / "child-finished"
        pid_file = self.directory / "child.pid"
        child = f"import time; from pathlib import Path; time.sleep(2.5); Path({str(marker)!r}).write_text('alive')"
        body = ("import subprocess\nfrom pathlib import Path\n" +
                f"child = subprocess.Popen([sys.executable, '-c', {child!r}])\n" +
                f"Path({str(pid_file)!r}).write_text(str(child.pid))\n" +
                "time.sleep(10)\n")
        tool = self.fake_tool(body)
        # Cleanup is also registered for a failing assertion in these tests.
        def cleanup():
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.addCleanup(cleanup)
        return tool, marker, pid_file

    def test_timeout_stops_descendants(self):
        tool, marker, pid_file = self.child_wrapper()
        result = MODULE.execute([tool], self.directory / "wrapper.log", 1.0, self.directory)
        self.assertEqual(result["error"], "command timeout")
        self.assertTrue(pid_file.exists(), "wrapper never started its child")
        time.sleep(2)
        self.assertFalse(marker.exists(), "descendant continued after command timeout")

    def test_runner_termination_stops_descendants(self):
        tool, marker, pid_file = self.child_wrapper()
        process = subprocess.Popen([sys.executable, str(RUNNER), "--vvp", tool,
                                    "--out", str(self.directory / "cancelled")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(pid_file.exists(), "simulation wrapper did not start")
            process.terminate()
            self.assertEqual(process.wait(timeout=5), 128 + signal.SIGTERM)
            time.sleep(3)
            self.assertFalse(marker.exists(), "descendant continued after cancellation")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


class ProcessCleanupTests(unittest.TestCase):
    def test_denied_group_signal_preserves_timeout_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'command.log'
            with mock.patch.object(MODULE.os,'killpg',side_effect=PermissionError('denied')):
                result=MODULE.execute([sys.executable,'-c','import time;time.sleep(10)'],log,0.05,Path(tmp))
            self.assertIn('command timeout',result['error'])
            self.assertIn('process group termination failed',result['error'])
            self.assertLess(result['seconds'],5)
            self.assertIn('RUNNER_ERROR',log.read_text())
            status,_=MODULE.classify(dict(checks=1,expected_failure='IRQ_SET_WINS'),result,'CHECK_FAIL IRQ_SET_WINS\n')
            self.assertEqual(status,'error')

    def test_cleanup_wait_is_bounded_and_does_not_mask_error(self):
        proc=mock.Mock(pid=12345)
        proc.wait.side_effect=subprocess.TimeoutExpired(['simulator'],5)
        with mock.patch.object(MODULE.os,'killpg'):
            error=MODULE.stop_process_group(proc)
        proc.wait.assert_called_once_with(timeout=5)
        self.assertIn('process cleanup incomplete',error)


if __name__ == "__main__":
    unittest.main()
