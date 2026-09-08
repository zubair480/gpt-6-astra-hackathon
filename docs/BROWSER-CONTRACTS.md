# Browser phase 1 integration contracts

Owner: coordination task in C:/AI/gpt-6-astra-hackathon. Version 1 proposed for
parallel implementation; report necessary changes before changing shared APIs.

## Detector (Session 3)

Export `ScreenshotDetector` from `plva.detection`:
`detect(png: bytes) -> list[dict]`, synchronous/local, each finding has `kind`,
`value`, `label`, `x`, `y`, `width`, `height`. Match PrivacySession.protect's current
contract. Optional confidence/source allowed. PNG pixels are the only source of
values. Constructor may warm local models; report provisioning and requirements.
Errors raise; never convert inference failure into an empty successful finding set.
Optional `scrub_text(text: str) -> str` may use the local classifier/patterns.

## Browser (Session 2)

Export `BrowserSession` from `plva.browser`, async API used on one owning event loop:
`start()`, `open(url)`, `capture() -> dict`, `tabs() -> list[dict]`,
`select_tab(tab_id)`, `execute(action, privacy)`, `close()`.
Capture returns `png: bytes`, `width`, `height`, `tab_id`, `url`, `title`.
URL/title are local metadata and must be scrubbed before sending or exporting.
Use a dedicated visible profile by default with constructor options for isolated
tests. Runtime owns capture->detect->protect and cloud calls; browser owns input
and checks immediately before privacy.resolve for token typing. Return a sanitized
execution summary with resolved token count. Do not use the DOM as detector input.
Navigation/tab APIs are local controls, not unrestricted cloud code execution.

## Viewer/server (Sessions 1 and 4)

Preserve existing /api/state, /api/audit, /api/run, /api/stop and /api/config fields.
Add to state: `browser: {status, active_tab_id, tabs:[{id,title,url}]}`,
`detector: {status, name, latency_ms, error}`, `source: 'web'|'fixture'`.
Browser metadata is operator-local; export/sending requires scrubbing.
New routes: POST /api/browser/open {url}, POST /api/browser/select {tab_id},
POST /api/browser/preview {}, POST /api/browser/close {}.
Open/select refresh preview; UI may poll preview when idle with a busy guard.
POST /api/run additionally accepts `source:'web'|'fixture'` (default web for new UI).
Existing rehearsal belongs to fixture mode and must stay explicitly labeled.
Audit entries retain existing fields and add request_id, frame_hash,
status ('prepared'|'sent'|'responded'|'failed'), response_id, response_model,
usage, actions (tokens only), error. Provider receipts are absent until returned.
Stop pauses agent work, not manual browser use; close explicitly closes the browser.

## Ownership and execution

Session 1 alone edits server.py/runtime.py and shared dependency files. Other
sessions report dependency requirements in their handoff instead of editing them.
Each lead uses its own task/worktree and subagents, reports evidence and changed
files to coordinator task 01a082f1-d26d-78e2-946d-87abf4bca5dc, and does not run or
restart the main localhost:18080 server. Integration owns that browser/server.
Do not commit .env or include keys in task messages. Reference submodule source
may be read from the main workspace if absent in the worker worktree.
