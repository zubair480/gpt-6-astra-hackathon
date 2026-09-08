"""Check the second-run handoff only; no browser is operated by this example."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from plva_skill_learning.common import read_json
from plva_skill_learning.runner_adapter import prepare_run


def inspect_mock_hook(prepared_context: dict, scenario: dict) -> dict:
    """Receive exactly what a core runner could receive and inspect fresh bindings.

    A changed-layout screenshot is a future runner input, not evidence that this
    hook understood or successfully operated that layout.
    """
    context = prepared_context.get("context") or {}
    parameters = context.get("parameters", {})
    hook_passed = (
        prepared_context.get("status") == "ready"
        and parameters.get("customer_shipping_address") == scenario.get("session_token")
        and parameters.get("order_id") == scenario.get("order_id")
        and all(check["result"] == "unknown" for check in context.get("checks", []))
    )
    return {
        "mock_hook": "passed" if hook_passed else "failed",
        "fresh_bindings_received": hook_passed,
        "changed_layout_input": list(scenario.get("layout_changes", [])),
        "actual_layout_adaptation": "pending",
        "live_runner": "pending",
        "note": "Only context handoff was checked. No application actions or visual adaptation ran.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_path")
    parser.add_argument("--bindings", default="fixtures/new-run-bindings.json")
    parser.add_argument("--scenario", default="fixtures/changed-layout/scenario.json")
    parser.add_argument("--capabilities", default="fixtures/capabilities.json")
    args = parser.parse_args()
    prepared = prepare_run(args.skill_path, read_json(Path(args.bindings)), read_json(Path(args.capabilities)))
    report = inspect_mock_hook(prepared, read_json(Path(args.scenario)))
    print(json.dumps(report, indent=2))
    return 0 if report["mock_hook"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
