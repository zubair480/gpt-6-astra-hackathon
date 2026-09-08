# PLVA desktop: multi-session, multi-agent execution plan

> Priority revised: [BROWSER-FIRST-MULTI-SESSION-PLAN.md](BROWSER-FIRST-MULTI-SESSION-PLAN.md)
> is now the active plan. Protecting Astra's observations on Amazon and other
> unmodified websites is Phase 1. This desktop plan is deferred to Phase 2; reuse
> completed browser privacy components and do not launch desktop-first work ahead
> of the browser acceptance milestone. The sequence below is retained for Phase 2.

## Objective

Build a demoable Windows computer-use agent with a local privacy layer. Astra
must read protected screenshots of real native applications, choose actions,
switch applications, and type locally resolved private values. Private information
must be found from screenshot pixels without DOM annotations or preloaded fixture
values. Keep the implementation small enough for the hackathon.

This replaces the browser-only delivery scope. The previous browser demo remains
a regression fixture, not the desktop deliverable. This document supersedes the
core execution sequence in WINDOWS-IMPLEMENTATION-PLAN.md.

## What exists and what changes

| Area | Starting point | Desktop work |
| --- | --- | --- |
| Astra | Real Responses API computer-action loop verified | Reuse provider connection; remove support-ticket-only instructions |
| Observation | Edge viewport + data-private DOM findings | Windows screen/window capture + local image-based findings |
| Execution | Playwright mouse/keyboard | Windows mouse/keyboard, focus, app switching and coordinate conversion |
| Privacy | Pillow masks and per-run memory vault | Reuse; consume OCR findings and scrub all outgoing text |
| Token gate | Demo URL + matching HTML field | Selected native-window scope + editable focus when available; explicit local fallback for ambiguous focus |
| Completion | Hard-coded replacement-form receipt | Workflow-specific local check against the actual saved output |
| Viewer | Browser screenshots and request log | Desktop frames, detected regions, API response receipts and actual action trail |
| Optional modules | Two teammate handoff documents | Keep Qwen/NemoClaw and skill generation independent of desktop readiness |

## Actual separate sessions

Each row below is a separate persistent Codex task with its own thread ID, lead,
working branch, progress report and handoff. Subagents belong inside those tasks.
Do not implement all rows as subagents of one task.

The present task can serve as Session 1. When execution is requested, create four
additional project tasks with the exact titles below. Check the current project
and checkout state first; include the current uncommitted implementation in the
starting snapshot so workers do not start from an obsolete default branch.
Use separate worktrees where supported. Keep secrets out of commits and handoff
messages; provision the local key only where live integration requires it.

| Session / task title | Larger goal | Subagents inside the task | Owns |
| --- | --- | --- | --- |
| 1. PLVA Desktop — Integration and Coordination | Deliver the integrated desktop loop and coordinate the other sessions | Contract reviewer; provider/history worker; integration reviewer, scheduled as capacity permits | plva/contracts.py, plva/runtime.py, plva/server.py, dependency files, shared status board |
| 2. PLVA Desktop — Windows Runtime | Capture and operate real Windows applications | Capture/DPI worker; input/focus worker | plva/desktop/, tests/test_desktop*.py |
| 3. PLVA Desktop — Screenshot Privacy | Find private content from pixels and connect it to the vault | OCR/regions worker; classification/scrubbing worker | plva/detection/, plva/privacy.py, tests/test_detection*.py, tests/test_privacy.py |
| 4. PLVA Desktop — Viewer and Demo | Make the real workflow visible, understandable and repeatable | Viewer/audit worker; native demo-fixture worker | static/, demo/desktop/, docs/DESKTOP-DEMO.md |
| 5. PLVA Desktop — Verification and Handoff | Independently verify the desktop result and prepare user testing | Privacy-evidence worker; Windows end-to-end/packaging worker | tests/desktop_e2e/, docs/DESKTOP-TEST-REPORT.md, docs/DESKTOP-USER-TESTS.md |

Subagents get concrete independent assignments, not open-ended duplicates of their
lead's job. Leads integrate their workers' changes and report to Session 1.
Creation of a task is not evidence that it has finished: collect its thread ID and
monitor it until its handoff or a specific blocker arrives.

Available execution slots limit simultaneous work. Queue subagents when capacity
is full; distinct persistent sessions do not imply unlimited parallel processes.
Session 1 remains responsive for integration and user updates.

## Session 1: integration and coordination

First deliver a small shared contract and an executable baseline. Do not build a
general plugin platform or a separate provider proxy unless the existing loop
actually requires one.

1. Read the current runtime, privacy module and reference interception path.
2. Separate capture, detection, model requests and action execution behind the
   contracts below. Keep the working browser route as an explicit test mode.
3. Freeze contract version 1 and dispatch Sessions 2–5 with their ownership.
4. Wire the existing Astra adapter to the desktop runtime and local detector.
5. Remove browser-ticket assumptions, the DOM field gate and hard-coded receipt
   check from desktop mode. Do not simply delete authorization checks; replace
   them with the chosen demo window/focus rule.
6. Scrub every outgoing text component at the send boundary. Preserve tokenized
   model actions in history; only a local execution copy receives actual values.
7. Record provider-returned response ID, returned model, usage and sanitized
   actions. Distinguish attempted requests, responses received and API failures.
8. Integrate worker branches deliberately; run shared checks after integration.

Exit: one protected native-app screenshot produces an actual Astra action that
executes on Windows, and the next native-app observation is protected again.

## Session 2: Windows runtime

Capture/DPI worker:

- Select and verify one local Windows screenshot backend. Test the actual machine
  before committing to a library; do not copy Apple-specific reference code.
- Return screenshot dimensions, physical origin and coordinate mapping. Pick one
  monitor as the initial demo surface; record its scaling setting.
- Detect changes in window position/focus and refresh before dependent actions.
- Ensure the operator's raw viewer is not inside the captured surface. Prefer a
  separate operator monitor; otherwise hide/minimize the viewer during desktop
  runs and use a global stop hotkey. Fail the capture if the operator panel becomes
  the foreground capture target. Do not recurse into the raw preview.

Input/focus worker:

- Implement click, double-click, move, scroll, keypress, text entry, screenshot and
  wait; implement drag if the chosen demo needs it. Unsupported actions must be
  reported, not silently ignored.
- Support Unicode typing, focus checks and real switching between selected apps.
- Resolve screen coordinates consistently with capture and DPI scaling.
- Add an immediate local emergency-stop control and prevent actions queued after
  cancellation. Restrict cleanup to processes/files owned by the demo.
- Use local window/focus metadata for execution checks when needed. Do not use
  accessibility text or clipboard reads as a hidden replacement for screenshot
  perception. Avoid leaving substituted values on the clipboard.

First proof: capture a native Notepad window, type a synthetic sentence, observe
the result, switch to another selected application, and stop through the hotkey.
These are backend tests, not a claim of Astra-driven completion.

Exit: Windows capture/input and coordinate conversion work on the demo monitor;
application switching and stop have been exercised on the actual machine.

## Session 3: screenshot privacy

OCR/regions worker:

- Inspect the reference's worker/findings interfaces and any reusable model
  artifacts before selecting a Windows-compatible local OCR path.
- Verify required model files exist, can be provisioned, and run on this machine.
  CPU is the baseline; Core ML, NVIDIA and NemoClaw must not be prerequisites.
- Take PNG bytes as input; return recognized text, boxes and confidence locally.
- Measure cold and warm processing on an actual native-app screenshot.
- Handle multiline text, modest font changes and window movement. Coordinates
  must match the original screenshot, including any OCR resize transform.

Classification/scrubbing worker:

- Detect email, phone and obvious secret patterns from OCR text.
- For names and addresses, implement explicit visible-label/context rules for the
  demo plus a local classifier if verified artifacts are readily available. State
  which path is used. Regex for email alone does not satisfy name/address coverage.
- Rules may use visible labels such as Name or Address; they must not hard-code
  customer values, file paths, pixel coordinates or fixture filenames.
- Feed findings into the existing masks/vault, preserve stable tokens between
  screenshots and protect values after they are typed into another application.
- Use known vault values as an additional local detection/scrubbing aid after the
  first discovery. Initial discovery must not come from a fixture-value list.
- Block sending on detector failure; expose failure clearly in the viewer.

Acceptance fixtures: synthetic native-app screenshots with changed name/email/
phone/address, a fake key, multiline address, moved window and a different font.
The checker may know expected values; the detector must not receive them.

Exit: PNG-only detection locates and masks supported private values on screenshots
from two native applications, including fresh values not known before the run.
Document misses instead of silently reverting to DOM annotations or cloud OCR.

## Session 4: viewer and demo

Viewer/audit worker:

- Reuse the current dashboard. Add clearly separate Desktop and Browser fixture
  modes; label Scripted rehearsal and Live Astra accurately.
- Show the source application, frame ID, detection count/time and protected frame.
- Tie request images to sent frames and display provider response receipts. Keep
  original action arguments tokenized in the activity trail.
- Expose start/stop/status and a protected evidence download. Do not display the
  API key or raw vault values in export data.
- Follow Session 2's operator-view exclusion arrangement so raw previews cannot
  be re-captured and forwarded upstream.

Native demo-fixture worker:

- Inventory native applications actually available. Baseline source is Notepad.
  Preferred destination is installed Excel; if absent, select a second installed
  native editor/spreadsheet application and record the choice before fixture work.
  A second native app is a required cross-application gate. Do not substitute a
  browser form without reporting that the desktop milestone is still incomplete.
- Prepare a small synthetic customer record as ordinary visible text with name,
  email, phone, address and an irrelevant fake key. No HTML privacy annotations.
- Task: read the record, switch to the destination app, fill a labeled customer
  summary, and save a local output. Do not send email, buy anything or upload files.
- Build an independent output checker that reads the saved artifact and compares
  the expected fields. The agent's completion message is not the success check.
- Make a second fixture with different values and a moved/resized window. Generate
  expected answers solely for verification, not as detector or agent inputs.

Exit: fixtures and output checker are ready; the viewer clearly distinguishes
raw local observation, protected observation, cloud request and execution result.

## Session 5: verification and handoff

Start independently with fixtures and tests; run integrated native tests after
Sessions 1–4 are ready. This task reports evidence, not just pass counts.

- Verify an unannotated native screenshot is the detector input.
- Check supported private regions are covered in the actual sent image; string
  searching JSON alone cannot establish that screenshot pixels are protected.
- Check outbound text and action history for the fixture's real values.
- Verify permitted tokens type the actual values locally and unknown/blocked
  tokens do not type. Verify a disallowed window and loss of focus stop execution.
- Force a detector error and verify no new model request is sent for that frame.
- Verify emergency stop, shifted window coordinates and the actual DPI setting.
- Run real Astra through the two-app workflow and check the saved artifact.
- Repeat once with fresh values and changed layout. Attribute scripted backend
  checks, mocked unit tests and live-model results separately.
- Verify PowerShell setup/start/stop and document required model downloads, the
  selected monitor, applications, API setup and the user test procedure.

Exit: a short test report names the applications, environment, outcome, actual
provider response IDs, remaining limitations and precise rerun instructions.

## Small shared contracts (Session 1 freezes exact Python types)

- Capture: `Frame(png, width, height, origin_x, origin_y, coordinate_map, window_id)`.
- Detect: `detect(png) -> findings` with kind, value, pixel rectangle, confidence
  and local detection source. Values are local-only.
- Protect: existing `PrivacySession.protect(png, findings)` returns protected PNG
  and a value-free manifest. Extra detector metadata stays local unless scrubbed.
- Execute: normalized Astra action plus local window scope and cancellation flag;
  token substitution occurs only inside the execution boundary.
- Observe/send: one send path accepts protected image bytes and scrubbed text.
  Record exactly that payload; authorization headers stay out of audit data.
- Audit: run ID, frame ID/hash, protected image, sent/request state, response ID,
  returned model, usage, tokenized action, execution outcome and timing.
- Verify: local checker returns success/failed plus value-free mismatch labels.

Do not silently change a shared contract. Propose the minimal diff to Session 1;
it updates the contract and notifies all affected sessions.

## Execution order and desktop ownership

1. Session 1 freezes contracts, creates the separate tasks and records their IDs.
2. Sessions 2, 3 and 4 develop independently; Session 5 writes verification fixtures.
3. Session 2 reserves a short desktop test window. Session 3 works on saved synthetic
   screenshots during that interval; other sessions must not drive the desktop.
4. Session 1 integrates a one-value native round trip as soon as capture and
   detection are ready. Fix this before expanding to the whole demo.
5. Session 4 supplies the native two-app scenario; Session 1 runs it with Astra.
6. Session 5 reserves the desktop for the independent acceptance runs.
7. Session 1 delivers the demo and user instructions with the actual status of
   each task. Optional friend integrations follow without blocking this result.

Only one session may control the real desktop at a time. Session 1 records the
desktop owner on the board and hands control off explicitly. Coding, image-only
tests and documentation continue in parallel. No concurrent mouse-driving agents.

## Tracking and handoff requirements

Create `docs/DESKTOP-STATUS.md` at execution start. Session 1 is its single writer.

| Session | Actual task ID | Branch/worktree | State | Evidence or blocker |
| --- | --- | --- | --- | --- |
| 1 Integration | Fill on dispatch | Fill on dispatch | Planned | Contracts pending |
| 2 Windows runtime | Fill on dispatch | Fill on dispatch | Planned | Native capture/input pending |
| 3 Screenshot privacy | Fill on dispatch | Fill on dispatch | Planned | Local OCR proof pending |
| 4 Viewer/demo | Fill on dispatch | Fill on dispatch | Planned | Native app inventory pending |
| 5 Verification | Fill on dispatch | Fill on dispatch | Planned | Acceptance runs pending |

States: planned, running, ready for integration, verifying, complete, blocked.
Every task handoff includes changed files, exact validation commands/results,
remaining limitations, contract changes and whether it currently owns the desktop.
Do not mark a session complete because its subagents finished coding.

## Hackathon finish line

Required: real Astra controls two native apps on Windows; supported private data
is found from screenshot pixels; cloud observations are masked; local typing uses
real values; later screenshots are masked again; output verification passes;
viewer proves which observations and actions were used; stop works.

Not required for this milestone: perfect coverage of every app/PII class, multiple
monitors, enterprise policy management, OS-wide sandboxing, a new model-training
project, cloud deployment, Qwen/NemoClaw integration or automatic skill generation.

If OCR/model availability or native app compatibility blocks the demo, report the
specific blocker and a reduced honest milestone. Do not relabel the existing
browser fixture as completed computer-use support.
