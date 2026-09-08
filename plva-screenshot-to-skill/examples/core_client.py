"""Thin local integration. Receives approved evidence and returns JSON, no actions."""
import argparse
import json
from pathlib import Path

from plva_skill_learning.api import SkillForge


def learn_and_prepare(bundle, bindings, capabilities, state, out, approval_store=None):
    forge = SkillForge(state, approval_store)
    imported = forge.import_recording(bundle)
    candidate = forge.draft_skill(imported["recording_id"], {"mode": "mock", "out": out})
    prepared = forge.prepare_run(candidate["path"], bindings, capabilities)
    # The host may now present the candidate and pass this context to its agent.
    # Its current observation, privacy, action, and approval policy stays authoritative.
    return {"candidate": candidate, "prepared": prepared}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", default="fixtures/shipment-demo")
    p.add_argument("--bindings", default="fixtures/new-run-bindings.json")
    p.add_argument("--capabilities", default="fixtures/capabilities.json")
    p.add_argument("--state", default="out/client-state")
    p.add_argument("--out", default="out/client-candidate")
    p.add_argument("--approval-store")
    args = p.parse_args()
    print(json.dumps(learn_and_prepare(args.bundle, json.loads(Path(args.bindings).read_text()),
                                     json.loads(Path(args.capabilities).read_text()), args.state, args.out, args.approval_store), indent=2))
