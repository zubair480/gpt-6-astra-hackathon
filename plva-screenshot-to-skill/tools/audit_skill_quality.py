"""Measure the same learning regressions against current and optional baseline code.

Run with the project's Python. This uses synthetic recordings and real draft,
export and prepare functions in isolated subprocesses, never application actions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TITLES = {
    "incidental_private_token_does_not_require_a_binding": "Ignore unrelated visible fields",
    "one_private_token_with_two_roles_requires_review": "Ask when one reference has two meanings",
    "conflicting_token_classes_require_review": "Do not guess conflicting field metadata",
    "one_public_value_with_two_roles_requires_review": "Ask when a public value has two roles",
    "failed_source_cannot_prepare_as_ready": "Reject an unsuccessful demonstration",
    "cancelled_source_cannot_prepare_as_ready": "Recognize a cancelled workflow",
    "unrecovered_failed_check_blocks_preparation": "Stop at an unresolved failed checkpoint",
    "corrected_typing_omits_superseded_wrong_write": "Learn the correction, omit the wrong entry",
    "corrected_typing_does_not_require_wrong_state": "Start from a valid state after correction",
    "recovered_historical_check_allows_corrected_workflow": "Keep failure evidence and allow verified recovery",
    "failed_click_validation_message_is_not_a_precondition": "Do not turn an error message into a prerequisite",
}


def worker(source):
    sys.path.insert(0, str(Path(source).resolve() / "src"))
    spec = importlib.util.spec_from_file_location("quality_cases", ROOT / "tests/test_skill_regressions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.SkillRegressionTests)
    ids = [test.id() for test in suite]
    result = unittest.TestResult()
    suite.run(result)
    failures = {test.id() for test, _ in result.failures}
    errors = {test.id() for test, _ in result.errors}
    skipped = {test.id() for test, _ in result.skipped}
    cases = []
    for test_id in ids:
        name = test_id.rsplit(".", 1)[1].removeprefix("test_")
        status = "error" if test_id in errors else "failed" if test_id in failures else "pending" if test_id in skipped else "passed"
        cases.append({"case_id": name, "title": TITLES.get(name, name.replace("_", " ")), "status": status})
    print(json.dumps({"totals": {status: sum(c["status"] == status for c in cases) for status in ("passed", "failed", "error", "pending")}, "cases": cases}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-commit")
    parser.add_argument("--out", type=Path, default=ROOT / "src/plva_skill_learning/data/quality-audit.json")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return 0

    def measure(source):
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(source)],
                                   capture_output=True, text=True, check=True, timeout=90)
        return json.loads(completed.stdout)

    current = measure(ROOT)
    baseline = measure(args.baseline) if args.baseline else None
    package = ROOT / "src/plva_skill_learning"
    report = {
        "kind": "synthetic_learning_regression_audit", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline_commit": args.baseline_commit, "baseline": baseline, "current": current,
        "source_hashes": {path.name: hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() for path in sorted(package.glob("*.py"))},
        "suite_hash": hashlib.sha256((ROOT / "tests/test_skill_regressions.py").read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "scope": "The same synthetic recording variations run through draft, export, and prepare. No live model or application execution.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"current": current["totals"], "baseline": baseline["totals"] if baseline else None, "report": str(args.out)}))
    return 1 if current["totals"]["failed"] or current["totals"]["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
