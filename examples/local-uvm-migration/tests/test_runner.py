"""Test missing evidence, schema changes and disabled-checker acceptance paths."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("migration_runner", Path(__file__).resolve().parents[1] / "run.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class MigrationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def test_original_goal_sets_and_zero_wait_exclusion(self):
        goals, excluded = M.required_goals(0)
        self.assertEqual(len(goals), 20)
        self.assertNotIn("bus/wait", goals)
        self.assertEqual([r["id"] for r in excluded], ["APB-WAIT"])
        for wait in (1, 3):
            goals, excluded = M.required_goals(wait)
            self.assertEqual(len(goals), 21)
            self.assertIn("bus/wait", goals)
            self.assertFalse(excluded)

    def test_trace_requires_every_input_and_cycle(self):
        inputs = [[0] * 7]
        good = "MIG_TRACE 1 " + " ".join(["0"] * 14) + "\n"
        self.assertEqual(M.parse_trace(good, inputs), [[0] * 14])
        for bad in ("", good + good, good.replace("TRACE 1", "TRACE 2"),
                    good.replace(" 0 0", " x 0", 1), good.replace(" 0 0", " 1 0", 1)):
            with self.subTest(output=bad):
                with self.assertRaises(ValueError):
                    M.parse_trace(bad, inputs)

    def test_migrated_goal_names_do_not_accept_padding_or_incomplete_lines(self):
        self.assertEqual(M.migration_goals("MIG_COVER cross/config/read\n"), {"cross/config/read"})
        for bad in ("MIG_COVER cross/config/ read\n", "MIG_COVER\n", "MIG_COVER name extra\n"):
            with self.assertRaises(ValueError):
                M.migration_goals(bad)

    def test_comparison_retains_field_and_cycle(self):
        old = [[0] * 14, [0] * 14]
        new = [r[:] for r in old]
        new[1][-1] = 1
        result = M.compare_traces(old, new)
        self.assertFalse(result["success"])
        self.assertEqual(result["differences"], 1)
        self.assertEqual(result["first_differences"], [dict(cycle=2, field="pending_after", legacy=0, uvm=1)])
        for a, b in (([], []), (old, new[:1]), ([[0]], [[0]])):
            with self.assertRaises(ValueError):
                M.compare_traces(a, b)

    def waveform(self, config_after="0"):
        names = ("rst_n", "psel", "penable", "pwrite", "paddr", "pwdata", "events",
                 "pready", "pslverr", "prdata", "config_value", "pending")
        codes = dict(zip(names, "ABCDEFGHIJKL"))
        declarations = "\n".join(f"$var wire 32 {key} {name} $end" for name, key in codes.items())
        initial = "\n".join(f"b0 {key}" for key in codes.values())
        return ("$timescale 1ps $end\n$scope module apb_tb $end\n" + declarations +
                "\n$upscope $end\n$enddefinitions $end\n#0\n" + initial +
                f"\n#15000\nb{config_after} K\n#16000\n")

    def test_legacy_waveform_distinguishes_pre_edge_and_post_update(self):
        path = self.directory / "wave.vcd"
        path.write_text(self.waveform("1"))
        records = M.legacy_trace(path, 1)
        self.assertEqual(records[0][10:14], [0, 0, 1, 0])
        result = M.compare_traces([[0] * 14], records)
        self.assertEqual(result["first_differences"][0]["field"], "config_after")

    def test_legacy_waveform_rejects_unknown_missing_and_truncated_evidence(self):
        path = self.directory / "wave.vcd"
        for bad in (self.waveform("x"), self.waveform().replace("$var wire 32 K config_value $end\n", ""),
                    self.waveform().replace("#16000\n", ""), self.waveform().replace("1ps", "1ns")):
            path.write_text(bad)
            with self.assertRaises(ValueError):
                M.legacy_trace(path, 1)

    def test_native_cover_inventory_actions_and_reachability(self):
        def row(label, count, source=None):
            source = source or M.HERE / "tb/top.sv"
            return f"C '\x01f\x02{source}\x01t\x02user\x01o\x02{label}\x01h\x02TOP.top.{label}' {count}\n"
        path = self.directory / "coverage.dat"
        labels = sorted(M.RESET_COVERS)
        good = "".join(row(label, 1) for label in labels)
        output = "".join(f"MIG_SVA_COVER {label}\n" for label in labels)
        path.write_text(good)
        self.assertEqual(M.reset_counts(path, output), dict.fromkeys(labels, 1))
        for bad, log in ((row(labels[0], 1), output), (good + row(labels[0], 1), output),
                         ("".join(row(label, 0) for label in labels), ""),
                         (good, output + "MIG_SVA_COVER unknown\n"),
                         (good.replace(str(M.HERE), "/wrong-source"), output), (good, "")):
            with self.subTest(data=bad, log=log):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    M.reset_counts(path, log)

    def valid_output(self):
        return ("Accellera:1800.2:UVM:2020.3.2\n"
                "UVM_WARNING a [NO_DPI_USED] expected\nUVM_WARNING b [NO_VISIT_CHECK] expected\n"
                "MIG_OWNERSHIP passive driver=0 sequencer=0 legacy=1\n"
                "MIG_COMPLETE samples=2 comparisons=2\nRESULT PASS checks=2\n"
                "UVM_WARNING : 2\nUVM_ERROR : 0\nUVM_FATAL : 0\n")

    def test_zero_comparison_wrong_ownership_and_native_error_rejected(self):
        case = dict(id="normal", checks=2, expected_failure=None)
        execution = dict(returncode=0, error=None)
        good = self.valid_output()
        self.assertTrue(M.evaluate(case, execution, good, "uvm")[0])
        for bad in (good.replace("comparisons=2", "comparisons=0"),
                    good.replace("driver=0", "driver=1"), good.replace("UVM_ERROR : 0", "UVM_ERROR : 1"),
                    good.replace("UVM_WARNING : 2", "UVM_WARNING : 3"),
                    good.replace("2020.3.2", "2020.3.1"), good + "RESULT PASS checks=2\n"):
            with self.subTest(output=bad):
                self.assertFalse(M.evaluate(case, execution, bad, "uvm")[0])

    def test_diagnostic_requires_exact_label_nonzero_and_no_timeout(self):
        case = dict(id="sva", checks=2, expected_failure="MIG_SYNC_RESET")
        log = "CHECK_FAIL MIG_SYNC_RESET\n"
        self.assertTrue(M.evaluate(case, dict(returncode=1, error=None), log, "uvm")[0])
        for execution, output in ((dict(returncode=0, error=None), log),
                                  (dict(returncode=1, error="timeout"), log),
                                  (dict(returncode=1, error=None), "CHECK_FAIL OTHER\n"),
                                  (dict(returncode=1, error=None), log + "CHECK_FAIL OTHER\n")):
            self.assertFalse(M.evaluate(case, execution, output, "uvm")[0])


if __name__ == "__main__":
    unittest.main()
