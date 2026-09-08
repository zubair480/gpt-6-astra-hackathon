"""Local CLI. JSON stdout is the integration boundary; preview is human-readable."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import SkillforgeError, read_json, write_json


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SkillforgeError("invalid_arguments", "Invalid command arguments. Run skillforge --help for usage.")


def parser():
    p = Parser(description="Draft evidence-backed skills locally. No computer actions are executed.")
    p.add_argument("--state", default=".skillforge", help="Local catalog directory")
    p.add_argument("--approval-store", help="External trusted core/user approval registry")
    commands = p.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="Validate and register an approved recording")
    imp.add_argument("bundle")
    approve = commands.add_parser("approve", help="Record an explicit local core/user approval; does not sanitize")
    approve.add_argument("bundle")
    approve.add_argument("--allow-cloud", action="store_true")
    approve.add_argument("--trust-role-hints", action="store_true")
    draft = commands.add_parser("draft", help="Create a candidate with deterministic mock or approved Astra")
    draft.add_argument("recording_id")
    draft.add_argument("--mode", choices=["mock", "astra"], default="mock")
    draft.add_argument("--out")
    for command in ["validate", "preview"]:
        commands.add_parser(command).add_argument("skill")
    rehearse = commands.add_parser("rehearse", help="Exercise local skill cases; never run applications")
    rehearse.add_argument("skill")
    rehearse.add_argument("--out")
    edit = commands.add_parser("edit", help="Apply a JSON patch object to a new revision")
    edit.add_argument("skill"); edit.add_argument("--patch", required=True); edit.add_argument("--out", required=True)
    accept = commands.add_parser("accept", help="Record review acceptance in a fresh folder")
    accept.add_argument("skill"); accept.add_argument("--out", required=True)
    export = commands.add_parser("export", help="Export a portable four-file skill folder")
    export.add_argument("candidate"); export.add_argument("--out", required=True)
    prep = commands.add_parser("prepare", help="Prepare guidance and fresh bindings; never execute")
    prep.add_argument("skill"); prep.add_argument("--bindings", required=True); prep.add_argument("--capabilities")
    prep.add_argument("--out")
    demo = commands.add_parser("demo", help="Run the synthetic import/draft/export/prepare demonstration offline")
    demo.add_argument("--out", default="out/demo")
    demo.add_argument("--fixtures", default="fixtures/hd")
    return p


def run(args):
    from .api import SkillForge
    from .ingest import approve_bundle
    from .review import preview, edit, accept
    forge = SkillForge(args.state, args.approval_store)
    if args.command == "import":
        return forge.import_recording(args.bundle)
    if args.command == "approve":
        return approve_bundle(args.bundle, forge.approval_store, allow_cloud=args.allow_cloud, role_hints_trusted=args.trust_role_hints)
    if args.command == "draft":
        return forge.draft_skill(args.recording_id, {"mode": args.mode, "out": args.out})
    if args.command == "validate":
        return forge.validate_skill(args.skill)
    if args.command == "rehearse":
        from .rehearsal import run_rehearsal
        result = run_rehearsal(args.skill)
        result["status"] = "needs_attention" if result["totals"]["failed"] else "complete"
        if args.out:
            write_json(Path(args.out), result)
        return result
    if args.command == "preview":
        # A local source pointer is optional. Export remains usable without it.
        recording = None
        wf = read_json(Path(args.skill) / "workflow.json")
        refs = forge._catalog()["recordings"]
        if wf.get("source_recording_ids") and wf["source_recording_ids"][0] in refs:
            from .ingest import import_bundle
            try:
                recording = import_bundle(refs[wf["source_recording_ids"][0]]["path"], forge.approval_store if forge.approval_store.exists() else None)
            except SkillforgeError:
                pass
        return preview(args.skill, recording=recording)
    if args.command == "edit":
        return edit(args.skill, read_json(Path(args.patch)), args.out)
    if args.command == "accept":
        return accept(args.skill, args.out)
    if args.command == "export":
        return forge.export_skill(args.candidate, args.out)
    if args.command == "prepare":
        result = forge.prepare_run(args.skill, read_json(Path(args.bindings)), read_json(Path(args.capabilities)) if args.capabilities else [])
        if args.out:
            write_json(Path(args.out), result)
        return result
    if args.command == "demo":
        from .safety import check_outbound
        root = Path(args.out).resolve()
        check_outbound(root.name)
        if root.exists():
            raise SkillforgeError("output_exists", "Demo output exists. Choose a new --out folder to preserve it.")
        fixtures = Path(args.fixtures)
        demo_forge = SkillForge(root / "local-state")
        summary = demo_forge.import_recording(fixtures / "shipment-demo")
        if summary["data_class"] != "synthetic":
            raise SkillforgeError("synthetic_required", "One-command demo accepts only the pinned synthetic fixture.")
        candidate = demo_forge.draft_skill(summary["recording_id"], {"mode": "mock", "out": str(root / "candidate")})
        report = demo_forge.validate_skill(root / "candidate")
        package = demo_forge.export_skill(candidate["candidate_id"], root / "export")
        context = demo_forge.prepare_run(root / "candidate", read_json(fixtures / "new-run-bindings.json"), read_json(fixtures / "capabilities.json"))
        write_json(root / "prepared-context.json", context)
        from .rehearsal import run_rehearsal
        rehearsal = run_rehearsal(root / "candidate")
        write_json(root / "rehearsal.json", rehearsal)
        (root / "review.txt").write_text(preview(root / "candidate"), encoding="utf-8")
        evaluation = {"demo_kind": "synthetic_offline", "generation": "deterministic_mock", "source_outcome": report["outcome"],
                      "package_validation": report["status"], "fresh_binding_preparation": context["status"],
                      "review_acceptance": "pending_user_review", "live_astra_synthesis": "not_run", "changed_layout_execution": "pending_main_runtime",
                      "privacy": {"reusable_skill_has_session_tokens": False, "image_redaction_verified": False},
                      "performance_improvement": "not_measured", "offline_rehearsal": rehearsal["totals"],
                      "changed_layout_input": str((fixtures / "changed-layout").resolve())}
        write_json(root / "evaluation.json", evaluation)
        from .demo_viewer import write_demo_viewer
        viewer = write_demo_viewer(root, fixtures)
        return {"status": "complete" if report["status"] != "invalid" and context["status"] == "ready" and not rehearsal["totals"]["failed"] else "needs_attention", "demo_kind": "synthetic_offline", "output": str(root), "viewer": str(viewer), "candidate": candidate["path"], "export": package, "prepared_status": context["status"], "rehearsal": rehearsal["totals"], "live_reuse": "pending_main_runtime"}
    raise SkillforgeError("unknown_command", "Unknown operation.")


def main(argv=None):
    try:
        result = run(parser().parse_args(argv))
        print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=True))
        if isinstance(result, dict) and result.get("status") in {"invalid", "error", "needs_input", "unsupported", "needs_attention"}:
            return 2
        return 0
    except SkillforgeError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        # Third-party/file errors may embed paths or untrusted source text.
        print(json.dumps({"status": "error", "code": "operation_failed", "message": "Operation could not complete. Check input files and output directory; no source content is echoed."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
