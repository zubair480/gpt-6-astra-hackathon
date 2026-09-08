# PLVA integration v1

## Scope and first handoff

Contract commit: `dbdd0ea` (local Git). These are independent workstream files. Nothing in the main team's repository was changed, and no message was sent to an unidentified team destination.

The core owns capture, complete-bundle sanitization, private-value resolution, current observations, and action approval. This module consumes a directory and returns procedure context. The checked-in synthetic fixture needs no other workstream.

The visual demo now defaults to `fixtures/hd`, a separate 2400×1440 recording named `recording-demo-hd-002`. The original `recording-demo-001` fixture, its files, and the v1 schemas remain unchanged. Both exact synthetic bundle hashes are pinned locally; neither is approved for cloud synthesis by default.

## Directory contract

`contracts/v1/manifest.schema.json` and `event.schema.json` define input. Each bundle contains `manifest.json`, the declared JSONL event file, and the declared frames. Schemas reject unknown properties and versions. Required event sequence is authoritative; gaps are warned about, duplicates rejected, timestamps may tie. Screenshots-only still needs ordered observation events. Missing order is a useful validation error rather than an invented sequence.

Optional `observation.public_values` is a v1 extension: `[{"value":"DEMO-104","role_hint":"order_id"}]`. It helps parameterize a public run-specific value. Private values use the example's `tokens` metadata. The producer must emit operations before token substitution. Token pattern in this prototype is `CLASS_number_hexnonce`, with a 4–32-character lowercase hex nonce.

Check evidence IDs must refer to observations or actions. A core or user check with no supporting evidence does not establish success. A model interpretation alone never establishes independently verified outcome. Corrections may link failed actions and observations. The local fixture contains 18 events, 7 frames, all four action statuses, a failed attempt, a user correction, and two source checks.

Import limits: manifest 1 MB; JSONL 16 MB; event 64 KB; 10,000 events; 1,000 frames; frame 10 MB; bundle 100 MB; 8,192 pixels per image side and 16 million pixels. PNG, JPEG, and static WebP are accepted. Paths are relative POSIX paths even on Windows. Traversal, aliases, links, junctions, missing frames, invalid hashes, and oversized data fail with sanitized errors. Extra undeclared files are not read or included in approval.

Exact-byte SHA-256 integrity: hash a canonical JSON object mapping every declared relative path (including manifest and events) to its file SHA-256; then hash that JSON. Canonical means sorted keys, separators `,`/`:`, ASCII JSON, UTF-8. Fixture bytes are protected from Git newline conversion. This is integrity, not authentication or proof of redaction.

## Local approval

This hackathon uses a small external local approval registry, not a new authentication system. The host/core chooses and protects the registry path. It must be outside the evidence bundle. A bundle's own `synthetic` or `sanitized` flag gives it no authority.

Only the exact checked-in fixture digest is pretrusted, with cloud disabled. Other bundles need an explicit core/user decision through `approve_bundle` or CLI `approve`. The entry binds digest, producer, data class, `allow_cloud`, and `role_hints_trusted`. Changing any declared file invalidates approval. Do not accept a registry supplied by an untrusted bundle. Anyone who can modify the trusted application or registry can change this local decision; multi-user authentication is outside this workstream.

```python
from plva_skill_learning.ingest import approve_bundle

# Called by the trusted local core AFTER full-bundle sanitization and approval.
approve_bundle(bundle_path, external_approval_store,
               allow_cloud=False, role_hints_trusted=True)
```

`role_hints_trusted=True` means the caller vouches for the metadata's roles. Without that, semantic private roles stay unresolved; token class cannot distinguish shipping from billing. This flag is not permission to execute. Cloud permission remains outside the skill package and is tied to exact evidence bytes.

The second outbound check runs before mock/live synthesis and export. It catches known test canaries, obvious email/key patterns, stale session tokens in reusable content, and several scope-escape patterns. It does **not** certify all private text, image pixels, or all prompt injections. Images must already be approved by the core. No vault or raw screenshot redaction is implemented here.

## Public Python/JSON operations

```python
from plva_skill_learning.api import SkillForge

forge = SkillForge(state_dir="local-learning-state",
                   approval_store="core-controlled/approvals.json")
summary = forge.import_recording(bundle_path)
candidate = forge.draft_skill(summary["recording_id"],
                              {"mode": "mock", "out": "output/candidate"})
report = forge.validate_skill(candidate["path"])
package = forge.export_skill(candidate["candidate_id"], "output/shared")
prepared = forge.prepare_run(candidate["path"], fresh_bindings, capabilities)
```

All returns are JSON-serializable. Summary includes recording ID, digest, capture mode, data class, counts, warnings, and an explicitly labeled outcome claim. Candidate includes ID, path, mode, revision, status, and package. Export returns path, four file names, and validation. The catalog stores local source pointers, not a copy of screenshots or permission grants. A reused recording ID with changed content is rejected.

`prepare_run` returns `ready`, `needs_input`, `unsupported`, or `invalid` following `prepared-context.schema.json`. The current runner supplies capabilities; omitting them does not assume capability. The example uses `observe`, `navigate`, `type`, `select`, and `click`. Private bindings must be fresh, class-matching opaque references; source-token hashes detect reuse. A syntactically fresh token is not proof it exists in the vault: the core must verify issuance and role before execution. Public bindings are bounded strings, never executable snippets.

Ready means the context was prepared. An unreviewed candidate stays labeled as such. The context includes current bindings, substituted procedure, and checks reset to `unknown`, so old success is not attributed to this run. It contains no action dispatcher and cannot issue permissions. Do not persist a prepared context as the reusable skill; it intentionally contains current-run references.

## Skill packages and review

The only exported files are `SKILL.md`, `workflow.json`, `evidence-map.json`, and `validation.json`. Output schemas are in `contracts/v1`. Source IDs are pointers that the host may resolve from its local recording catalog; frames are not copied. Missing local evidence is reported in preview, while the portable procedure remains readable.

Every normal step maps to event/frame evidence with an observed/inferred/user-confirmed basis. Recovery includes its own event references. Generation records mock versus Astra, model ID, bundle digest, and window count. Sessions' original tokens are replaced by parameters and stored only as hashes for stale-binding checks. No session approval enters the package.

Review edits are shallow JSON field replacements, not RFC 6902. Editable fields: title, objective, parameters' roles/required flags, preconditions, capabilities, step wording, and questions. Source facts, identities, recorded checks, and recovery evidence are protected. Edited wording becomes user-confirmed. Every edit creates a new revision and invalidates old reruns. Acceptance creates a reviewed copy; it does not install or execute anything. Edit through the review command, since Markdown must match the structured workflow.

Validation separates package structure/text checks, demonstrated source outcome, review, and reruns. V1 emits candidate/reviewed status. `validated_on_fixture` is reserved in the schema; it is not issued by this module without a future run-result integration. The generated sample is a candidate. Local rerun records are inspectable assertions, not authenticated attestations or permission.

## Model adapter and bounded recordings

Mock synthesis is deterministic and evidence-derived. It does not understand unseen screenshot pixels: without text/actions it produces conservative state transitions and review questions. Astra refines a fixed evidence-backed step set using approved images and text; checks, parameter roles, capabilities, and source facts are retained by local code. Failed actions become recoveries, not mandatory failed steps. Exact duplicate frames are collapsed for display while every event ID is retained; small image changes are preserved.

Timeline windows contain 24 events by default with 4-event overlap. Stable step IDs deduplicate overlaps; live requests use the action anchor to choose a window. Schema bounds still limit a candidate to 256 steps/checks; segment larger tasks into separate recordings. This is a bounded demo, not unlimited-video processing.

Adapter documentation checked against official [image inputs](https://developers.openai.com/api/docs/guides/images-vision) and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). REST uses `GET /v1/models/gpt-6-astra` followed by `POST /v1/responses`, structured JSON, approved image data URLs, and `store:false`. No SDK, Qwen, server, or fallback model. Actual account access was not exercised in this delivery. Refusal, incomplete output, unauthorized bundle, missing key, or model mismatch fails locally with a sanitized error.

## What the main team must connect

1. Emit one real approved v1 recording and independently sourced checks.
2. Supply current-run token bindings and runtime capabilities.
3. Feed prepared guidance plus the current screenshot into the existing Astra runtime.
4. Execute the changed-layout case under core policy and record real rerun outcome evidence.

`examples/changed_run.py` tests only the JSON handoff with a mock. It explicitly does not claim to inspect or operate the changed layout. No speedup or generalized reliability claim has been measured.
