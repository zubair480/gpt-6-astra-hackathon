# PLVA reference review and simplification

Reviewed source: `reference/browser-agent-privacy-layer`, commit `467a452`.
This is a source review, not a reproduced live Holo/Astra run or a security certification. The missing Git LFS baseline archive and unavailable model assets still prevent a complete reference deployment. Tests described below were read, not run during this review.

## Recommendation

Keep the reference's privacy architecture: local screenshot detection, opaque masks, session tokens, a memory-only vault, outbound text scrubbing, checked action resolution, and an exact outgoing-request viewer. Adapt the provider/runtime boundary for Astra. Remove the optional generative local model and its NemoClaw/OpenShell deployment from the first version.

Replace automated credential decisions with explicit grants or deterministic policies. Keep blocked data blocked. Defer open-ended natural-language computation over hidden values; use small fixed local functions only when the task requires them. This preserves the core private-use workflow, but does not reproduce every semantic capability of the local model.

## Actual request and response path

1. `run_agent.sh` starts the proxy and launches the external `holo-desktop-cli` with a local provider base URL. HoloDesktop itself is not implemented in this repository.
2. `proxy.py:create_app` handles `/v1/chat/completions`. Request hooks run before the HTTP client sends the rewritten body upstream.
3. `frame_redaction_hook` scans image parts throughout message history, decodes them, calls the redactor, and substitutes the protected PNGs. This is not just latest-frame processing.
4. `AcceleratedRedactor` owns a persistent local worker, enforces its request/response protocol, checks outputs, and caches results in memory.
5. `VaultRedactor` consumes OCR findings containing text, class, spans, and bounds. Allowed values enter `SessionVault`; blocked values remain masked without resolvable tokens. Placeholder chips are painted onto already-redacted pixels.
6. `privacy_request_hook` replaces known private values in message text, applies the semantic classifier to user/tool content, and injects instructions plus a manifest containing tokens/classes/policy levels rather than values. Exact known-value replacement also covers assistant/system text; semantic classification is deliberately narrower.
7. The proxy sends the transformed request. Its audit stores retain protected frame bytes and the transformed request body.
8. The model response is recorded before local token resolution. `privacy_response_hook` parses action JSON from `choices[].message.content` and resolves tokens in executed fields, excluding reasoning and final-answer fields.
9. The runtime receives the rewritten action and can type the real value. Subsequent screenshots and history pass through the protection path again.
10. When action rewriting applies, streaming responses are assembled before checking and rewriting, then re-emitted. This avoids forwarding half-validated action content.

## Essential components to retain

| Component | Source | Why it matters |
| --- | --- | --- |
| Request/response interception | `src/plva_proxy/proxy.py` | Places checks before transmission and action delivery. |
| Vault and grants | `src/plva_proxy/privacy.py:SessionVault` | Stable tokens, policy checks, scoped expiry/use counts, unknown-token rejection. |
| Masking and token chips | `privacy.py:VaultRedactor` | Removes private pixels while keeping the task usable. |
| History scrub | `privacy.py:HistoryScrubber` | Prevents restored action values from leaking on later turns. |
| Action-only resolution | `privacy.py:privacy_response_hook` | Keeps model-visible reasoning tokenized while executing authorized uses. |
| Frame and call audit | `proxy.py:FrameStore`, `CallStore` | Lets the operator inspect the actual outgoing images and content. |
| Per-class policy | `config/privacy-policy.json` | Separates hidden-but-usable, approval-gated, and blocked information. |

## What NemoClaw is actually doing

`run_mediator_sandbox.sh` starts a Docker/OpenShell environment, uploads a Qwen GGUF and llama.cpp server, applies the network policy, probes denied outbound connections, and forwards the model endpoint to host loopback. This is a separate local-model service, not the screenshot redactor or the vault.

The optional model supplies:

- Credential-use judgments through `Mediator.decide_approval`.
- Behavior reviews through `Mediator.review_trace`, triggered by a deterministic suspicious-event threshold.
- Instruction-based sort/select through `SemanticExecutor`.

The normal proxy wiring constructs the local model client only if privacy tools or the mediator are enabled. Basic privacy hooks do not require it. In the automatic approval bridge, the request carries the token, class, action context, and task summary; that bridge does not populate the optional cleartext field. Semantic execution does resolve values locally and expose them to the local model.

The executor's raw model answer can contain real values. It validates the answer against its input values, converts the answer back to issued tokens, and exposes only that token result to the remote agent. Removing the generative model removes this particular cleartext-model trust boundary. Removing only its sandbox while still running it would not preserve the same network isolation.

## Simplifications supported by the code

| Reference feature | First-version replacement | Capability change |
| --- | --- | --- |
| Qwen approval judgments | A local Allow once/Deny control or explicit task policy | Loses free-form automatic policy interpretation. |
| Model watchdog | Stop button and deterministic repeated-denial limit | Loses semantic review of behavior. |
| Natural-language private sort/select | Fixed local operations, or defer | Arbitrary reasoning over hidden values is unavailable. |
| NemoClaw/OpenShell model deployment | Omit along with the generative local model | No local-model isolation service is needed. |
| Multiple detectors and experimental training trees | Choose one local OCR/classification pipeline | Avoids training and backend-selection scope. |
| Many diagnostic toggles | One protected default mode | Retain failures as blocking events. |
| Holo-specific marker teaching/probes | Adapt to the selected Astra action contract | Requires integration testing rather than a string-only model swap. |

`POST /viewer/approvals` already supports explicit local grants without the mediator. `ToolChannel._deterministic_sort` already sorts private values locally and returns tokens without consulting a model. These are existing architectural seams, not a new product direction.

## Important details for the adaptation

- **Astra compatibility is an interface question.** Provider presets currently contain H Company and Overshoot. The launcher requires the external Holo runtime, and response resolution expects its action envelopes. Changing the provider URL/model name alone does not establish that Astra's responses execute correctly. Keep the privacy core; verify or adapt the request and action formats.
- **Windows requires redactor work.** The complete history classifier is exposed through the Vision worker. `AcceleratedRedactor.classify_texts` explicitly rejects the browser worker. The browser worker supplies masks and summary regions, but its report does not supply the OCR values needed by the current vault wrapper. Reusing that path requires adding both findings and text-classification support, not simply selecting WASM.
- **Choose one local detection path.** OCR plus a local PII classifier and deterministic secret rules can retain the reference approach without custom visual-detector training. The reference already permits disabling its visual detector. Evaluate the resulting coverage; this changes detection capability.
- **Destination hints are not verified UI destinations.** `_call_target` reads origin/URL/target fields from the returned action. If we promise site-bound credential use, our executor must independently validate the actual destination or use a human-confirmed action. A model-supplied destination string alone is insufficient.
- **The network monitor is reactive.** `egress_verify.monitor` polls sockets and terminates processes after detecting an external connection. It is not equivalent to a preventive firewall. The repository's separate macOS PF setup is optional/manual. Do not claim polling proves zero bytes escaped.
- **The inspector has a sensitive side.** Frame/call views use protected outgoing content, but `/viewer/vault` returns real values and `/viewer/findings` can contain OCR text. Keep those operator surfaces outside agent access; preferably omit cleartext viewer endpoints from the first version.
- **Memory-only has a scope.** The vault is a process-memory dictionary cleared on disposal. This is not cryptographic memory erasure. The legacy one-shot redactor writes a raw frame to a temporary directory, and Holo run artifacts are cleaned up after the run. Use the in-memory worker path if claiming no raw screenshots are written by PLVA.
- **Protection must be enabled.** The launcher defaults redaction off. A simplified version should default protection on and never silently switch to an unprotected mode.
- **Fail-closed is not perfect recall.** An error can block transmission, but an undetected secret can still survive a successful detector call. Measure supported classes and fixtures explicitly.

## Tests worth preserving in the new integration

The reference tests cover stable token issuance, blocked classes, expired/wrong-context approvals, atomic resolution, clipped-value remasking, stale manifests, history re-scrubbing, unknown-token rejection, and buffered streamed actions. Integration tests use synthetic findings and an in-process upstream server; they verify privacy plumbing, not real OCR accuracy or actual model behavior.

The first Astra proof should show: a protected observation reaches the API; Astra emits a usable placeholder action; the local executor inserts the correct value; the next observation/history still contains no raw value; and a protection failure produces no upstream request. Keep the viewer tied to those actual outgoing payloads.

## Implementation sequence

1. Verify the smallest Astra-compatible observation/action exchange and determine whether HoloDesktop can execute it or needs an adapter.
2. Select and validate one local detector path on the target machine, including OCR findings and text classification.
3. Connect vault, masks, manifests, history scrub, and action-only resolution end to end.
4. Add explicit local approvals and a stop control; omit the optional generative local model.
5. Expose only the protected outgoing-request inspector and exercise failure/denial paths.

This review changes no reference source code. The user-supplied hackathon rules about pre-existing code remain a separate submission consideration; architecture reuse and code reuse should not be conflated.
