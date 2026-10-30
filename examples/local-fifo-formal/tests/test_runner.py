"""Reject incomplete proofs, unrelated failures and missing model evidence."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

RUNNER = Path(__file__).resolve().parents[1] / "run.py"
SPEC = importlib.util.spec_from_file_location("formal_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormalEvidenceTests(unittest.TestCase):
    def execution(self, code=0, error=None):
        return dict(returncode=code, error=error)

    def test_proof_requires_induction_completion(self):
        case = MODULE.plan(0)[0]
        self.assertEqual(MODULE.judge(case, self.execution(), "PASS", "", [])[0], "error")
        self.assertEqual(MODULE.judge(case, self.execution(), "PASS", "successful proof by k-induction", [])[0], "pass")

    def test_missing_unknown_error_timeout_are_not_success(self):
        case = MODULE.plan(0)[0]
        for status in ("MISSING", "UNKNOWN", "ERROR", "TIMEOUT"):
            self.assertEqual(MODULE.judge(case, self.execution(), status, "", [])[0], "error")
        self.assertEqual(MODULE.judge(case, self.execution(0, "command timeout"), "PASS", "successful proof by k-induction", [])[0], "error")

    def test_status_and_exit_code_must_agree(self):
        case = MODULE.plan(0)[0]
        self.assertEqual(MODULE.judge(case, self.execution(1), "PASS", "successful proof by k-induction", [])[0], "error")
        mutant = MODULE.plan(0)[3]
        self.assertEqual(MODULE.judge(mutant, self.execution(0), "FAIL", "Assert failed in fifo_formal: ap_data", ["trace.vcd"])[0], "error")

    def test_mutant_needs_intended_assertion_and_trace(self):
        case = MODULE.plan(0)[3]
        expected = "Assert failed in fifo_formal: ap_data"
        self.assertEqual(MODULE.judge(case, self.execution(2), "FAIL", expected, ["trace.vcd"])[0], "detected")
        self.assertEqual(MODULE.judge(case, self.execution(2), "FAIL", expected, [])[0], "error")
        self.assertEqual(MODULE.judge(case, self.execution(2), "FAIL", "Assert failed in fifo_formal: ap_flags", ["trace.vcd"])[0], "error")
        self.assertEqual(MODULE.judge(case, self.execution(), "PASS", "", [])[0], "fail")

    def test_normal_cover_needs_every_goal_and_witness(self):
        case = MODULE.plan(0)[2]
        log = "\n".join(f"Reached cover statement in step 5 at fifo_formal: {name}" for name in MODULE.COVERS)
        self.assertEqual(MODULE.judge(case, self.execution(), "PASS", log, ["trace.vcd"])[0], "pass")
        self.assertEqual(MODULE.judge(case, self.execution(), "PASS", log, [])[0], "error")
        partial = log.splitlines()[0]
        self.assertEqual(MODULE.judge(case, self.execution(), "PASS", partial, ["trace.vcd"])[0], "error")

    def test_overconstraint_detection_is_not_arbitrary_fail(self):
        case = MODULE.plan(0)[-1]
        log = "\n".join(f"Unreached cover statement at fifo_formal: {name}" for name in MODULE.COVERS)
        self.assertEqual(MODULE.judge(case, self.execution(2), "FAIL", log, [])[0], "detected")
        self.assertEqual(MODULE.judge(case, self.execution(2), "FAIL", "crash", [])[0], "error")
        self.assertEqual(MODULE.judge(case, self.execution(2), "FAIL", log + "\nAssert failed in fifo_formal: ap_reset", [])[0], "error")

    def test_compiled_inventory_rejects_missing_assert_and_extra_assume(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.json"
            cells = [dict(name=n, parameters=dict(FLAVOR=f))
                     for f, names in (("assert", MODULE.CONTROL), ("cover", MODULE.COVERS),
                                      ("assume", {"as_initial_reset"})) for n in sorted(names)]
            model = dict(modules=[dict(cell_sorts=[dict(type="$check", cells=cells)])])
            path.write_text(json.dumps(model))
            case = MODULE.plan(0)[0]
            self.assertEqual(set(MODULE.inspect_model(path, case)["assert"]), MODULE.CONTROL)
            cells[:] = [c for c in cells if c["name"] != "ap_count"]
            path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):
                MODULE.inspect_model(path, case)
            cells.append(dict(name="ap_count", parameters=dict(FLAVOR="assert")))
            cells.append(dict(name="unreviewed_assumption", parameters=dict(FLAVOR="assume")))
            path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):
                MODULE.inspect_model(path, case)

    def test_missing_tool_fails_cli_and_all_junit_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "result"
            missing = str(Path(temp) / "missing-tool")
            proc = subprocess.run([sys.executable, str(RUNNER), "--sby", missing,
                                   "--yosys", missing, "--out", str(out)],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            report = ET.parse(out / "junit.xml").getroot()
            self.assertEqual(report.attrib["errors"], "8")
            self.assertEqual(len(report.findall("testcase/error")), 8)
            self.assertFalse(json.loads((out / "summary.json").read_text())["success"])


if __name__ == "__main__":
    unittest.main()
