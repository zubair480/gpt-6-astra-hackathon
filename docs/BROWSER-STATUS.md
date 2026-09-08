# Browser-first implementation status

Updated September 8, 2026. Priority: ordinary websites through PLVA, then native
computer use. This is a Windows hackathon demo. Active plan:
[BROWSER-FIRST-MULTI-SESSION-PLAN.md](../BROWSER-FIRST-MULTI-SESSION-PLAN.md).

Latest fresh rerun: [FLOW-TEST-REPORT.md](FLOW-TEST-REPORT.md). After fixing a
Windows startup file-lock race, 108 default checks passed (14 opt-in skips),
all 3 real-site privacy tests passed, actual dashboard Start/Stop/Close passed,
and the strengthened live Astra token workflow completed with 6 real responses.
Its post-type pixel proof is tied to the actual later submitted request.

| Session | Actual task ID | State | Deliverable/evidence |
| --- | --- | --- | --- |
| 1 Integration â€” Review project | 01a082f1-d26d-78e2-946d-87abf4bca5dc | Complete for browser demo | Ordinary-site runtime/API, actual Astra provider boundary, integration |
| 2 Real Websites and Navigation | 01a08326-19cd-7c52-ba8e-7364dfeb4d24 | Imported | Visible Edge, URLs/tabs/actions, extension isolation, bounded capture recovery |
| 3 Local Screenshot Privacy | 01a08326-4e41-7a81-bc66-a02f757e0a48 | Imported | PNG-only CPU OCR, contextual detection, local vault/masks; 10 independent PNG checks passed |
| 4 Preview and Evidence Viewer | 01a08326-6a29-7843-b55f-a55409d93901 | Imported and verified | Local preview vs actual submitted images, response IDs/hashes; actual two-request export rendered and verified |
| 5 Independent Verification | 01a08326-bfa7-7ce0-a85f-db8dd86dd101 | Complete for tested demo scope | Pixel oracles, real-site samples, receipt validation, failure/stop regression checks |

These are four separate implementation tasks plus the original integration task.
Each implementation lead used two subagents. Worktrees are respectively e32e,
07c1, 6eed and e723 under C:/Users/aliam/.codex/worktrees. Integration owns the main
server/browser at localhost:18080. Workers use isolated profiles and coordinated
heavy-test windows.

## Working and measured

- Ordinary sites open in a dedicated Edge session. Detection reads screenshot
  pixels, without website privacy annotations or DOM values.
- Local English OCR assets are provisioned by start.ps1; inference runs on CPU.
- Actual Astra completed Amazon â†’ example.com in two successful HTTP 200 requests.
  Returned model: gpt-6-astra. It navigated and correctly reported Example Domain.
- Both submitted PNGs match their recorded SHA-256 hashes and audit images.
  Independent verification and the viewer session checked the protected export.
  This public navigation run does not by itself prove private-content detection.
- Separate real HTTPBin and Selenium samples demonstrated email glyph masking.
- The latest lightweight integration run: 85 tests, 81 passed, 4 explicit opt-in
  skips, zero failures. This excludes actual browser and OCR acceptance runs.
- Browser worker: 10 capture diagnostics tests passed; two focused real Edge
  minimized/scroll/manual-tab checks passed after the latest fixes.
- Stop during observation or a provider response, and observation failures,
  are covered by isolated boundary probes. Mocks prove those boundary cases,
  not live provider connectivity.

## Integration fixes and remaining acceptance

Astra rejected the initial navigation followup format. Protected images now live
inside function tool outputs; the complete real API run succeeded after this fix.
Windows capture can require bringing the selected page forward. It now retries
once after a 5-second screenshot timeout, independent of navigation's 30 seconds.

A real form-token attempt was interrupted by machine-installed Edge extensions
opening onboarding tabs. The actual origin gate correctly refused the unrelated
site. The dedicated browser now disables extensions. The exact public-form retry
passed, followed by a real-Astra token run: five successful responses, four
distinct protected frames, 845 independently checked initial email glyph pixels,
and one locally resolved email matching the verifier value. Astra then scrolled
and navigated to example.com. Plaintext test email and API key were absent from
all exported request text. Separate actual post-token pixel checks passed.

An earlier minimized-window test failed during a mixed-load suite; its exact
cause was not captured. The later focused two-test run passed. OCR clipping or
transcription misses remain possible and are recorded in the independent report.
Do not claim universal protection, a 120ms runtime, or native desktop support.

## Operator evidence

- Local export: .plva-evidence/amazon-example-live.json (Git-ignored).
- Export SHA-256: 9ccbd86208a9d97464afe4475c134fd6ef19ffee15c2de21da9337dd11fafa93.
- First response: resp_07744b585abea20e006aa093064f1c87d08ec4d2d80da4022a.
- Followup: resp_07744b585abea20e006aa0932d7ce487d0855f4253ea211842.

See [user test instructions](BROWSER-USER-TESTS.md) and
[independent evidence and limitations](BROWSER-TEST-REPORT.md).
Native desktop, Qwen/NemoClaw and screenshot-to-skill work remain separate phases.

## Final browser acceptance

- HTTPBin local token retry passed (17.918s): exact email typing, actual next-frame
  masking, phone masking, and unknown/secret-token rejection.
- Same-session two-origin transition test passed (21.929s): HTTPBin email masked
  before/after a 65px scroll; fresh Selenium-tab email masked; navigation to
  example.com; return to the first tab with its email still masked. Stop prevented
  token insertion. This test used real websites but made no provider call.
- Actual five-call Astra run: .plva-evidence/httpbin-astra-token-live.json,
  SHA-256 a28365ea660f669ccfdf80c6e3cb910c9618d1eb6846ffcc6da41aacb8c635ae.
  It verifies initial private glyphs and exact local typed value; its submitted
  followup image was also visually inspected. The independent full post-type
  pixel measurement belongs to the separate local form test, not this run.
- Main server reloaded with extension isolation and 5-second capture recovery.
  Local operator previews remain separate from saved API evidence.

The tested browser demo is complete. Detection can miss text or overmask labels;
Amazon account pages and every site/layout are not certified. Native desktop is
still phase 2. No Qwen/NemoClaw or skill-learning dependency was added.
