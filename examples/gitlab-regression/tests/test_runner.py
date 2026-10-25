"""Exercise the CLI, real simulator, error classification, and JUnit gate."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


RUNNER = Path(__file__).resolve().parents[1] / "run.py"


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
        ids = [node.attrib["name"] for node in junit.findall("testcase")]
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
        self.assertEqual(summary["functional"]["pass"], 28)
        self.assertEqual(summary["mutations"]["detected"], 2)
        self.assertEqual(junit.attrib["failures"], "0")
        self.assertEqual(junit.attrib["errors"], "0")
        self.assertEqual(len(junit.findall("testcase")), 30)

    def test_nightly_adds_recorded_random_sequences(self):
        process, summary, _ = self.invoke("--profile", "nightly", "--seed", "73")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(summary["functional"]["pass"], 31)
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
        self.assertEqual(len(junit.findall("testcase/failure")), 8)
        self.assertEqual(summary["mutations"]["detected"], 2)

    def test_missing_compiler_is_error_not_detected_mutation(self):
        process, summary, junit = self.invoke("--iverilog", str(self.directory / "missing-compiler"))
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(junit.findall("testcase/error")), 30)
        self.assertEqual(summary["mutations"]["detected"], 0)

    def test_timeout_is_error_not_detected_mutation(self):
        tool = self.fake_tool("time.sleep(2)\n")
        process, summary, junit = self.invoke("--vvp", tool, "--timeout", "0.05")
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(junit.findall("testcase/error")), 30)
        self.assertEqual(summary["mutations"]["detected"], 0)

    def test_zero_exit_without_completion_is_error(self):
        tool = self.fake_tool("print('simulation stopped without a completion record')\n")
        process, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(junit.findall("testcase/error")), 30)
        self.assertEqual(summary["mutations"]["detected"], 0)

    def test_unrelated_failure_does_not_kill_expected_mutations(self):
        tool = self.fake_tool("print('CHECK_FAIL IRQ_UNRELATED')\nsys.exit(1)\n")
        process, summary, junit = self.invoke("--vvp", tool)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(summary["mutations"]["error"], 2)
        self.assertEqual(summary["mutations"]["detected"], 0)
        self.assertEqual(len(junit.findall("testcase/error")), 2)


if __name__ == "__main__":
    unittest.main()
