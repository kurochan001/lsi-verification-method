"""Writes the results of a runner as JSON (the --json option of the run_*.py
scripts), which tools/results_history.py turns into the nightly report.

The file holds one object:

    {"simulator": "icarus", "name": "Icarus Verilog",
     "version": "Icarus Verilog version 13.0 (stable) (v13_0)",
     "tests": {"ch6/test_x": {"status": "pass"},
               "ch7/test_y": {"status": "fail", "reason": "output differs"}}}

The keys of "tests" are the paths under tests/ without ".sv". A status is one
of:

    pass         the output matches the expected output
    fail         it does not, or the test could not be built or run
    known        it does not, and the expected output was not recorded with
                 this simulator (a known difference, see README.md)
    unsupported  the simulator reported a construct it does not support yet,
                 or it cannot run this kind of test

New runner JSON also records generated_at, runner_sha256, runner_changed and
configuration. Each test has inputs_sha256 only when its input fingerprint is
unchanged between the start and end of execution; otherwise inputs_changed is
true. Consumers that only need statuses can continue to read older JSON.

It also holds what the runners share about the tests: how they are found,
and the metadata fields that change how a test is run and judged
(:should_fail_because:, :expected_exit:, :expected_stderr_regex:, :args:,
:files:, :defines:, :incdirs: and :top_module:, see "Metadata" in
README.md).
"""

import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ("pass", "fail", "known", "unsupported")


def test_id(test: Path) -> str:
    path = test.resolve()
    return path.relative_to(ROOT / "tests").with_suffix("").as_posix()


def find_tests(root: Path = ROOT) -> list[Path]:
    """Every test of the suite. Other .sv files under tests/ are sources that
    tests name in :files:, and their names do not start with "test_"."""
    return sorted((root / "tests").rglob("test_*.sv"))


def header(test: Path) -> dict[str, str]:
    """The fields of the metadata comment at the top of a test."""
    m = re.search(r"/\*(.*?)\*/", test.read_text(encoding="utf-8"), re.DOTALL)
    if not m:
        return {}
    return {k: v.strip() for k, v in re.findall(r"^:(\w+):\s*(.*)$", m.group(1), re.MULTILINE)}


def files(test: Path) -> tuple[list[Path], list[Path]]:
    """The files that :files: names next to the test: the sources (.sv and .v)
    that are compiled before the test, in the order written, and the include
    directories: those of the other files, which the design includes with
    `include, then those that :incdirs: names, relative to the test."""
    fields = header(test)
    sources, include_dirs = [], []
    for name in fields.get("files", "").split():
        path = (test.parent / name).resolve()
        if path.suffix in (".sv", ".v"):
            sources.append(path)
        elif path.parent not in include_dirs:
            include_dirs.append(path.parent)
    for name in fields.get("incdirs", "").split():
        path = (test.parent / name).resolve()
        if path not in include_dirs:
            include_dirs.append(path)
    return sources, include_dirs


def defines(test: Path) -> list[str]:
    """The macros that :defines: sets before the first source, each NAME or
    NAME=VALUE, which every runner passes in the form its simulator takes
    (-D or +define+)."""
    return header(test).get("defines", "").split()


def top_module(test: Path) -> str | None:
    """The top-level module that :top_module: names, or None to let the
    simulator take every module that nothing instantiates (23.3.1)."""
    return header(test).get("top_module") or None


def run_args(test: Path) -> list[str]:
    """The arguments that :args: gives the simulation, such as plusargs."""
    return header(test).get("args", "").split()


def judge_illegal(test: Path, accepted: bool, messages: str) -> tuple[bool, str]:
    """For a test with :should_fail_because:, whether the simulator rejected
    the design as it should, given whether it accepted it and the messages it
    printed: a line of them must say "error" (in any case) and match
    :expected_stderr_regex:, which names the place of the error."""
    if accepted:
        return False, "the design was accepted, but it is illegal"
    regex = header(test).get("expected_stderr_regex")
    if regex is None:
        return False, "no :expected_stderr_regex:"
    lines = messages.splitlines()
    if any(re.search(regex, l) and "error" in l.lower() for l in lines):
        return True, ""
    first = next((l.strip() for l in lines if "error" in l.lower()), "")
    return False, f"no error matches {regex!r}" + (f"; the first is: {first}" if first else "")


def judge_run(test: Path, returncode: int, messages: str) -> str:
    """Why the exit code of a simulation or its messages are not what
    :expected_exit: and :expected_stderr_regex: say, or "" if they are (or
    the test has neither). "nonzero" asks for an exit code above 0: a run
    killed by a signal does not end with an error code."""
    fields = header(test)
    want = fields.get("expected_exit")
    if want is not None and not (returncode > 0 if want == "nonzero"
                                 else returncode == int(want)):
        return f"exit code {returncode}, expected {want}"
    regex = fields.get("expected_stderr_regex")
    if regex is not None and not re.search(regex, messages, re.MULTILINE):
        return f"no message matches {regex!r}"
    return ""


def tool_version(command: list[str]) -> str:
    """The first line a tool prints for its version option, or "" if it fails."""
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = (r.stdout or r.stderr).strip().splitlines()
    return lines[0].strip() if lines else ""


def first_difference(got: str, want: str) -> str:
    """Where an output first differs from the expected output, for the reason
    of a failure, such as "line 3 is 'a=1', expected 'a=0'"."""
    def quote(line: str) -> str:
        return repr(line if len(line) <= 60 else line[:57] + "...")
    got_lines, want_lines = got.splitlines(), want.splitlines()
    for n, (g, w) in enumerate(zip(got_lines, want_lines), 1):
        if g != w:
            return f"line {n} is {quote(g)}, expected {quote(w)}"
    n = min(len(got_lines), len(want_lines)) + 1
    if len(got_lines) < len(want_lines):
        return f"line {n} is missing, expected {quote(want_lines[n - 1])}"
    if len(got_lines) > len(want_lines):
        return f"line {n} is extra: {quote(got_lines[n - 1])}"
    return "the line ends differ"


def input_files(test: Path) -> list[Path]:
    """The design, declared helpers/data, literal includes and expectation.

    Macro-selected includes and externally supplied data must be declared in
    :files:. Include directory contents are hashed conservatively, so changing
    an include's search precedence also invalidates old execution evidence.
    Missing declared files are hashed as missing, rather than silently omitted.
    """
    test = test.resolve()
    fields = header(test)
    paths = {test}
    for name in fields.get("files", "").split():
        paths.add((test.parent / name).resolve())
    for field in ("dpi_c", "vpi_c"):
        value = fields.get(field, "")
        if value:
            paths.add((test.parent / value.removeprefix("@")).resolve())
    expected = fields.get("expected_stdout", "")
    if expected.startswith("@"):
        paths.add((test.parent / expected[1:]).resolve())
    _, include_dirs = files(test)
    for directory in include_dirs:
        if directory.is_dir():
            paths.update(p.resolve() for p in directory.rglob("*") if p.is_file())
    pending = list(paths)
    while pending:
        source = pending.pop()
        if not source.is_file() or source.suffix not in (".sv", ".v", ".svh", ".vh", ".c", ".h"):
            continue
        for name in re.findall(r'(?:`include|#\s*include)\s*"([^"\n]+)"',
                               source.read_text(encoding="utf-8", errors="replace")):
            candidates = [source.parent / name, *(d / name for d in include_dirs)]
            included = next((p.resolve() for p in candidates if p.is_file()), None)
            if included is not None and included not in paths:
                paths.add(included)
                pending.append(included)
    return sorted(paths)


def input_digest(test: Path) -> str:
    """Hash input names and contents, independent of the checkout directory."""
    digest = hashlib.sha256()
    for path in input_files(test):
        # Repository-relative names keep the digest portable between CI/local.
        name = path.relative_to(ROOT).as_posix()
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file()
                      else b"MISSING")
    return digest.hexdigest()


def runner_digest(simulator: str) -> str:
    """Invalidate result evidence when the runner or normalization changes."""
    digest = hashlib.sha256()
    for name in (f"run_{simulator}.py", "suite_results.py", "normalize_output.py"):
        path = ROOT / "tools" / name
        digest.update(name.encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def fingerprints(tests: list[Path]) -> dict[str, str]:
    """Capture inputs before execution; write() checks them again afterward."""
    return {test_id(t): input_digest(t) for t in tests}


def write(path: Path, simulator: str, name: str, version: str,
          results: dict[str, tuple[str, str]], *,
          inputs: dict[str, str] | None = None, configuration: dict | None = None,
          runner_sha256: str | None = None) -> None:
    """results maps a test id to its status and the reason for it."""
    tests = {}
    for test, (status, reason) in sorted(results.items()):
        assert status in STATUSES, status
        tests[test] = {"status": status, **({"reason": reason} if reason else {})}
        if inputs is not None:
            current = input_digest(ROOT / "tests" / (test + ".sv"))
            if inputs.get(test) == current:
                tests[test]["inputs_sha256"] = current
            else:
                tests[test]["inputs_changed"] = True
    data = {"simulator": simulator, "name": name, "version": version, "tests": tests}
    if inputs is not None:
        data.update({"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "runner_sha256": runner_sha256,
                     "runner_changed": runner_sha256 != runner_digest(simulator),
                     "configuration": configuration or {}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
