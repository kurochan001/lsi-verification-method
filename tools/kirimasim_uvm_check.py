#!/usr/bin/env python3
"""Check whether kirimasim can process the pinned UVM library yet.

This is a signpost, not a gate. kirimasim does not support UVM today, so the
expected outcome is a report that says so. A report is written for every
outcome, and only a problem in this script itself exits non-zero. A pass here
means parsing or lowering only: no UVM test has been run.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from kirimasim_results import cell  # noqa: E402

ROOT = TOOLS.parent
PLAN_URL = ("https://github.com/kurochan001/lsi-verification-method/blob/main/"
            "docs/case-study-kirimasim/README.md#kirimasimがuvmに対応したら")
PROBE = "module uvm_parse_probe;\n  import uvm_pkg::*;\nendmodule\n"
LABELS = {"pass": "**通過**", "unsupported": "未対応", "crash": "**クラッシュ**",
          "timeout": "**時間切れ**", "not-run": "未実行"}
ERROR = re.compile(r"^(?:(?P<file>[^\s:][^:]*):(?P<line>\d+):\d+: )?(?:kirimasim: )?error: (?P<message>.*)$")
MESSAGE_KINDS = 5


def commands(kirimasim, uvm_home, probe):
    src = uvm_home / "src"
    tb = ROOT / "examples/local-uvm/tb"
    common = ["--timescale=1ns/1ps", f"-I{src}", "+define+UVM_NO_DPI"]
    return [dict(id="parse", label="UVMライブラリの解析",
                 command=[kirimasim, "parse", "--top=uvm_parse_probe", *common,
                          src / "uvm_pkg.sv", probe]),
            dict(id="lower", label="`local-uvm`のlowering",
                 command=[kirimasim, "--dump-sir", "--top=top", *common, f"-I{tb}",
                          src / "uvm_pkg.sv", tb / "apb_if.sv", tb / "uvm_apb_pkg.sv",
                          ROOT / "examples/local-apb/rtl/apb_regs.sv", tb / "top.sv"])]


def short_path(name, cwd, uvm_home):
    """kirimasim prints paths relative to its working directory; show stable ones."""
    path = (cwd / name).resolve()
    for base in (uvm_home.resolve(), ROOT):
        if path.is_relative_to(base):
            return str(path.relative_to(base))
    return path.name


def diagnostics(text, cwd, uvm_home):
    """Return error messages with the file and line of the first one."""
    found = [m for m in map(ERROR.match, text.splitlines()) if m]
    messages = Counter(m["message"] for m in found)
    first = next((m for m in found if m["file"]), None)
    where = f"{short_path(first['file'], cwd, uvm_home)}:{first['line']}" if first else None
    return messages, where


def classify(returncode, messages):
    if returncode < 0 or returncode >= 128:
        return "crash"
    return "pass" if returncode == 0 and not messages else "unsupported"


def run_check(check, uvm_home, out, timeout):
    argv = [str(part) for part in check["command"]]
    started = time.monotonic()
    row = dict(id=check["id"], label=check["label"])
    try:
        done = subprocess.run(argv, cwd=out, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        row.update(status="timeout", returncode=None, messages={}, first_error=None)
    except OSError as error:
        row.update(status="not-run", returncode=None, messages={}, first_error=None,
                   reason=f"{type(error).__name__}: {error.strerror}")
    else:
        text = done.stdout + "\n" + done.stderr
        (out / f"{check['id']}.log").write_text(text)
        messages, where = diagnostics(text, out, uvm_home)
        row.update(status=classify(done.returncode, messages), returncode=done.returncode,
                   messages=dict(messages), first_error=where)
    row["seconds"] = round(time.monotonic() - started, 1)
    return row


def errors_cell(row):
    if row.get("reason"):
        return cell(row["reason"])
    kinds = Counter(row["messages"]).most_common(MESSAGE_KINDS)
    if not kinds:
        return "なし"
    text = "、".join(f"`{cell(message)}`が{count}件" for message, count in kinds)
    if row["first_error"]:
        text += f"。最初は`{cell(row['first_error'])}`"
    return text


def lowering_passed(report):
    return any(row["id"] == "lower" and row["status"] == "pass" for row in report["checks"])


def render(report):
    lines = ["## kirimasimのUVM対応の確認", "",
             f"{cell(report['version'])}で、固定版のUVM {report['uvm']}を処理できるかを確かめます。"
             "下の107構成の合否には影響しません。", ""]
    if report["reason"]:
        lines += [f"実行していません（{cell(report['reason'])}）。", ""]
    else:
        lines += ["| 確認 | 結果 | 終了コード | 時間 | エラー |", "| --- | --- | ---: | ---: | --- |"]
        for row in report["checks"]:
            code = "" if row["returncode"] is None else row["returncode"]
            lines.append(f"| {row['label']} | {LABELS[row['status']]} | {code} | "
                         f"{row['seconds']:g}秒 | {errors_cell(row)} |")
        lines.append("")
    statuses = {row["status"] for row in report["checks"]}
    # The parse alone passes on every Linux build, so only the lowering is a signal to act on.
    if lowering_passed(report):
        lines += [f"**`local-uvm`のloweringが通りました。[UVM例の実行の進め方]({PLAN_URL})を確認してください。**"
                  "通過はUVMのテストを実行したことを意味しません。", ""]
    if statuses & {"crash", "timeout"}:
        lines += ["クラッシュと時間切れは、未対応とは別の問題です。kirimasimのバグかどうかを確認してください。", ""]
    return "\n".join(lines) + "\n"


def tool_version(kirimasim, timeout):
    try:
        return subprocess.run([str(kirimasim), "--version"], capture_output=True, text=True,
                              errors="replace", timeout=timeout).stdout.strip() or "kirimasim"
    except (OSError, subprocess.TimeoutExpired):
        return "kirimasim"


def check(kirimasim, uvm_home, out, timeout):
    out.mkdir(parents=True, exist_ok=False)
    report = dict(version=tool_version(kirimasim, 30), uvm=uvm_home.name, reason=None, checks=[])
    if not (uvm_home / "src/uvm_pkg.sv").is_file():
        report["reason"] = "固定版のUVMを用意できませんでした"
    elif not os.access(kirimasim, os.X_OK):
        report["reason"] = "kirimasimを実行できませんでした"
    else:
        probe = out / "uvm_parse_probe.sv"
        probe.write_text(PROBE)
        report["checks"] = [run_check(item, uvm_home, out, timeout)
                            for item in commands(kirimasim, uvm_home, probe)]
    (out / "uvm-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (out / "uvm-check.md").write_text(render(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kirimasim", type=Path, required=True)
    parser.add_argument("--uvm-home", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300, help="seconds for each check")
    args = parser.parse_args()
    report = check(args.kirimasim.resolve(), args.uvm_home.resolve(), args.out.resolve(), args.timeout)
    if lowering_passed(report):
        print(f"::notice title=kirimasim UVM::local-uvm lowering passed. See {PLAN_URL}")
    for row in report["checks"]:
        if row["status"] in ("crash", "timeout"):
            print(f"::warning title=kirimasim UVM::{row['label']}: {row['status']}")
    print("UVM check:", {row["id"]: row["status"] for row in report["checks"]} or report["reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
