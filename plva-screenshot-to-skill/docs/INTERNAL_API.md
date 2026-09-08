# Frozen implementation interfaces

Input/output contracts: contracts/v1/*.schema.json. Public JSON boundary wraps these interfaces.

`ingest.import_bundle(bundle_path, approval_store=None) -> recording` where recording is a dict with `manifest`, `events` ordered by sequence, `bundle_path` absolute string, `bundle_digest`, `approval` dict (allow_cloud, role_hints_trusted), `warnings` list. Default synthetic trust registry is packaged data/trusted-synthetic.json. External store must be outside the bundle; bundle flags never establish trust. `ingest.approve_bundle(bundle_path, approval_store, allow_cloud=False, role_hints_trusted=False)` is an explicit local core/user decision, not a sanitizer. Same digest algorithm as tools/seed_contracts.py. Reimport immediately before synthesis for TOCTOU protection.

`timeline.build_timeline(recording, window_size=24, overlap=4) -> dict` with `events`, `observations`, `windows` (each list of complete events), `warnings`. Preserve full events; dedup observation displays conservatively and retain event IDs. `timeline.evidence_map(recording, workflow) -> dict` matches evidence-map schema.

`synthesis.draft(recording, mode='mock', options=None) -> workflow` matches workflow schema. No persisted authority grants. Deterministic mock is evidence-derived, no hardcoded event IDs. Only executed actions become observed normal steps; failures/corrections recovery. Missing private roles yield unresolved private parameters; source tokens stored only as hashes in workflow. Options may provide a mocked transport for tests. Live mode calls only approved bundles, does not substitute another model.

`exporter.write_package(workflow, evidence_map, output_path) -> dict` writes exactly SKILL.md, workflow.json, evidence-map.json, validation.json to a fresh output directory; calls `validation.validate_data(workflow, evidence_map)` and outbound guard before creating files. `exporter.render_skill(workflow) -> str` deterministic Markdown, no scripts.

`validation.validate_data(workflow, evidence_map) -> validation report` and `validation.validate_skill(skill_path) -> report` implemented by lead. No exceptions for invalid candidate (report invalid); file reading can throw sanitized SkillforgeError. `safety.check_outbound(value, allow_tokens=False)` raises sanitized SkillforgeError for canaries, private patterns, unsafe instructions; `safety.findings(value, allow_tokens=False) -> list[str]` returns safe constant codes. These are heuristics, not proof of text or image redaction.

`review.preview(skill_path, recording=None) -> str`, `review.edit(skill_path, patch: dict, output_path) -> dict`, `review.accept(skill_path, output_path) -> dict`. Patch is shallow workflow fields only with identity/generation/evidence status fields protected; edits increment revision/reset acceptance/invalidate reruns. No mutations in place.

`runner_adapter.prepare_run(skill_path, bindings:dict, capabilities:list[str]) -> dict` matches prepared-context schema. Returns needs_input/unsupported/invalid/ready; rejects old token hashes and plain private values. Has no execution hooks or credential resolution. Runtime receives context only and retains authority.

Module ownership: evidence agent ingest.py/timeline.py/tests/test_evidence.py; synthesis agent synthesis.py/exporter.py/model_adapter.py/tests/test_synthesis.py; review agent review.py/runner_adapter.py/tests/test_review_runner.py/examples/changed_run.py. Lead owns safety.py/validation.py/api.py/cli.py/contracts/tools and integration docs, global tests. Agents do not edit STATUS.md; report updates to lead.
