# Windows implementation plan for PLVA

> Active priority: follow [BROWSER-FIRST-MULTI-SESSION-PLAN.md](BROWSER-FIRST-MULTI-SESSION-PLAN.md).
> Ordinary websites with PLVA-protected Astra input come first; native desktop
> control follows. This document retains earlier platform investigation context.

> Implementation update: the user subsequently narrowed this to a demoable hackathon
> build. The first Windows browser rehearsal now works: local annotated-field
> detection, screenshot masking, token resolution, form submission, receipt masking,
> and outgoing-request viewer. Twelve tests pass. Live Astra completed the demo in
> four API calls on September 8, 2026. General OCR, desktop control, Qwen/NemoClaw and skill synthesis
> remain outside this first implementation. See README.md for the runnable scope.
> The more extensive gates below describe the earlier plan, not completed features
> or prerequisites for running this scoped demo.

## Decision and verification level

The five-session plan is feasible as a Windows-targeted implementation, but the reference repository does not run unchanged on Windows. This document makes the platform decisions and acceptance gates explicit. It does not certify a working application: the core application, real detector inference, and Astra action loop are not yet integrated or tested.

Primary target: native Windows 11 x64. Keep the PLVA core and screenshot-to-skill module independent of WSL, Docker, NVIDIA hardware, and Apple libraries. The optional Qwen/NemoClaw service has a separate deployment path.

Checked on the user's machine during this review:

| Check | Observed result |
| --- | --- |
| OS | Windows 11 Pro, 64-bit |
| Python | 3.12.10 |
| Node | 24.18.1 |
| uv | 0.12.1 |
| Git | 2.55.0.windows.3 |
| Graphics reported by Windows | Intel Iris Xe; no NVIDIA device reported by this query |
| ONNX Runtime in the inspected Python | Imports successfully, version 1.20.1; CPUExecutionProvider available |
| Image handling | Pillow created, masked, and encoded a synthetic PNG in memory successfully |
| Playwright in the inspected Python | Not installed; this does not establish whether a separate Node/project installation exists |
| WSL | Command exists; distribution/version/readiness not verified |
| Docker | Command not found on PATH; installation/running status not established |

The image smoke check establishes image-library operation, not screenshot capture, OCR recall, or privacy efficacy. ONNX provider availability is not a successful model-inference test. Pin project dependencies rather than relying on global packages.

## Required platform substitutions

| Reference component | Windows implementation decision |
| --- | --- |
| Apple Vision OCR and Core ML/ANE | Local OCR and semantic model through explicitly selected CPU ONNX Runtime initially. Select, provision, and test exact model artifacts before treating this path as ready. |
| Multiple visual/OCR model experiments | One validated local path; keep detector interface independent of hardware. Do not reduce to regex alone while claiming names/addresses are covered. |
| HoloDesktop and Holo response grammar | Session 2 verifies Windows availability and Astra action compatibility immediately. If unusable, adapt a Windows-native runtime behind the same privacy contracts; preserve the privacy core rather than depend on an unavailable binary. |
| Browser capture and actions | Playwright with a dedicated local browser session is the initial proposed Windows demo target. It provides browser-page capture/actions; it does not control native Excel or PowerPoint. |
| Whole-desktop capture/actions | Separate runtime acceptance gate for Windows screenshot/input backend, DPI scaling, multi-monitor coordinates, foreground focus, and permissions. Do not present browser success as proof of native application support. |
| Bash launchers, .venv/bin paths, brew, open -a | Cross-platform Python entrypoints and short PowerShell wrappers; use .venv/Scripts only where needed. No Bash prerequisite for the core. |
| Unix process groups, signals, lsof, pfctl | Track owned child processes and use Windows-compatible lifecycle controls, with Job Objects where required. Explicit stop control; do not copy Unix kill/cleanup logic. |
| Optional macOS firewall | Separate Windows enforcement design if preventive network isolation is claimed. A localhost bind or socket polling is not an OS sandbox. |
| Qwen/NemoClaw ARM64 launcher | Optional separately verified WSL 2/Linux deployment; do not reuse the reference's hard-coded ARM64 binary. |
| Viewer and skill bundles | Local web UI plus portable JSON/PNG/Markdown; Windows path and encoding tests required. |

The reference's browser/WASM worker is not a complete Windows replacement today: its vault/history integration needs OCR value findings and classify_texts support. The complete reference history path explicitly requires its Vision worker. Assign that missing interface work to Session 3.

## Five core sessions with Windows deliverables

| Session | Goal and agents | Windows-specific exit gate |
| --- | --- | --- |
| 1. Architecture and coordination | Contract agent, integration agent, review agent; freeze observation/action/audit contracts and coordinate worktrees. | Bootstrap and integration commands work from PowerShell. No mandatory Apple/POSIX paths. Shared interfaces define image dimensions, token fields, errors, and cancellation. |
| 2. Astra and computer execution | API agent, runtime agent, action-gate agent. | Real synthetic Astra observation/action round trip on Windows; actual destination checked before token use; stop/cancellation prevents further actions. Browser versus desktop support explicitly recorded. |
| 3. Local privacy engine | Detection agent, vault/policy agent, history-scrub agent. | Real local OCR/classification on selected fixtures using CPU; screenshot and text protection both work; unknown tokens, invalid grants, and processing failures block. No implicit remote execution provider. |
| 4. Viewer and demo | Viewer agent, workflow agent, controls agent. | Viewer works in Windows browser and renders the actual outgoing protected content. Operator controls are outside the captured agent page. Ports and browser profiles do not collide between runs. |
| 5. Verification and release | Privacy-test agent, end-to-end agent, packaging agent. | Windows-local end-to-end checks and Windows CI for portable checks; clean install/start/stop tested; no orphaned owned processes or raw debug artifacts. |

These are logical sessions. Available agent slots are environment-dependent: do not assume all five sessions can each launch three agents simultaneously. Use bounded delegation as capacity allows, distinct file ownership, and one lead responsible for integration. Prefer one session doing the integrated visible demo at a time; separate browser profiles/ports for independent tests. Never have multiple agents drive the same native desktop concurrently.

## Three workstreams and Windows integration

1. **PLVA + Astra:** the five sessions above deliver the native Windows core. It must start and complete its supported demo with the optional local-model service disabled.
2. **Qwen + NemoClaw:** separate teammate follows FRIEND-HANDOFF-PRIVATE-REASONING.md. NVIDIA documents NemoClaw on Windows through WSL 2. Startup/provisioning is separate from the core; local forwarding/authentication and actual egress denial require testing. Do not assume a Windows-host inference daemon is inside the sandbox merely because NemoClaw connects to it. Keep all cleartext-processing components within the intended verified boundary. This machine has no verified NVIDIA acceleration; CPU feasibility or a teammate's suitable machine must be evaluated.
3. **Screenshot-to-skill:** separate teammate follows FRIEND-HANDOFF-SKILL-LEARNING.md. Import/export, mock synthesis, validation, and prepare-run must work natively on Windows. Evidence comes from PLVA; no desktop capture or Qwen dependency is required. Test Unicode paths, spaces, JSONL encoding, and portable relative frame paths.

## Build sequence and go/no-go gates

### Gate A: platform proof before broad implementation

Session 1 creates isolated dependency setup and contracts. In parallel:

- Session 2 installs/provisions the selected browser/runtime, tests a synthetic capture and input, then verifies Astra access and an action round trip. Reuse prior verified official Astra documentation; confirm the actual chosen API/runtime contract at implementation time.
- Session 3 loads the exact locally stored OCR and classifier models using CPUExecutionProvider and tests one screenshot plus one text observation. Measure cold/warm latency instead of inheriting the reference's 120 ms claim.
- Session 5 establishes synthetic fixtures and the outbound-request capture/assertion harness.

If either runtime or detection proof fails, resolve that specific dependency before claiming the plan is ready for full parallel implementation. Mock development can continue independently, clearly labeled.

### Gate B: one protected value end to end

Detect one synthetic email -> mask and assign token -> send protected observation to Astra -> validate returned action -> resolve token locally -> verify target input -> protect next screenshot/history. Inspect actual outgoing payloads. This must work without Docker, WSL, Qwen, or NemoClaw.

### Gate C: failure and lifecycle behavior

Test invalid tokens, expired/wrong-destination grants, model timeout, redactor failure, cancellation during inference, and repeated observations. Confirm no raw fallback or late action execution. Stop only processes owned by the run; do not kill unrelated user browsers or applications.

### Gate D: demo and teammate integration

Complete one supported Windows workflow, render the audit, export a sanitized evidence bundle to the skill module, and prepare a fresh skill run. Integrate the optional reasoning service only after its own readiness and isolation tests pass. Native Excel/PowerPoint claims require their separate desktop gate and actual application tests.

## Packaging and operating requirements

- Use project virtual environments and lockfiles. CPU is the baseline; GPU acceleration is optional and must not change privacy semantics.
- Use pathlib or equivalent, UTF-8 explicitly, binary PNG handling, portable relative paths, and short worktree locations such as C:/AI/plva-wt/<session>.
- Provide Python/Node entrypoints callable from PowerShell; avoid Bash-only environment assignment and command chaining in npm scripts.
- Launch owned background helpers without disruptive terminal windows. Provide explicit stop/status commands and cleanup on failure.
- Use memory-only captures in the privacy path. Disable raw screenshot/video/trace logging in browser tooling; permit persistent sanitized skill evidence only under the agreed export policy.
- Bind local operator services to loopback and keep operator-only credentials/endpoints unavailable to the agent. Loopback alone is not an authorization boundary.
- Pin CPUExecutionProvider explicitly for private inference; availability of another provider does not authorize using it.
- Do not claim full runtime isolation until preventive restrictions are implemented and tested. Keep the agent's action interface narrow; unrestricted generated shell/browser code can create channels outside the sanitization path.
- Session 5 documents what Windows-local, CI, mocked, model-backed, and manual native-app tests actually ran.

## Sources checked

- Playwright installation/system requirements: https://playwright.dev/docs/intro (Windows 11+ supported; compatible current Node versions documented).
- ONNX Runtime Python builds: https://onnxruntime.ai/docs/get-started/with-python.html (Windows x64 CPU package supported).
- NVIDIA Windows preparation: https://docs.nvidia.com/nemoclaw/user-guide/openclaw/get-started/additional-setup/windows-preparation (WSL 2, Ubuntu and container setup; NemoClaw commands run inside WSL).
- Local reference: coreml-redactor/src/plva_coreml/coreml_session.py, src/plva_proxy/redactor.py, redactor-worker/src/worker.js, run_agent.sh, and run_mediator_sandbox.sh.

Conclusion: proceed with the Windows-specific architecture and gates above. Platform feasibility is supported; end-to-end application readiness remains to be demonstrated in Gate A/B.
