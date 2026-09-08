# Browser viewer user tests

Use the dashboard served by the integrated browser runtime. The dedicated,
visible PLVA browser is the protected session. Existing personal browsers and
other AI tools are outside this boundary. The dashboard itself is never the
capture source. Raw screenshots, tab URLs and titles are operator-local data.

## Start the integrated app

On Windows with Python 3.12+ and Microsoft Edge, open PowerShell in the integrated
repository and run `./start.ps1`. It creates `.venv`, installs the requirements,
provisions the pinned English OCR assets, and starts the local server. First-time
installation/provisioning needs network access; OCR inference runs locally on CPU.
Open `http://127.0.0.1:18080` after startup succeeds. Do not launch a second copy
over a running integration server. Ctrl+C in its terminal stops the server.

No API key is needed for local previews. For a live run, expand **Astra connection**,
enter the authorized key locally, and choose **Save locally**. UI-entered keys are
held in runtime memory and cleared on restart. Do not include keys in evidence.
Use **Open website**, the **Managed tab** selector and **Refresh preview** before
**Start live Astra**. The **Old fixture rehearsal** section remains a separate
scripted regression workflow.

## Detector limits

The integrated detector uses local screenshot OCR and pattern/context
classification for email, phone, names, addresses and credential-like text.
Names and addresses need visible context or a supported pattern. Small text,
unusual fonts, low contrast, crop edges, handwriting and unsupported scripts can
be missed. OCR may mask a region yet transcribe its value incorrectly; review
exact spelling before relying on local token insertion. High confidence and an
empty token list do not certify a page as safe. See
[detector measurements](../plva/detection/README.md) for measured coverage.

## 1. Inspect before sending

1. Keep Astra stopped. Enter `https://www.amazon.com/` in the browser URL field
   and open it through PLVA. Handle any login or CAPTCHA directly in that browser.
2. Verify the selected tab and active origin correspond to the actual page.
   The local protected preview should refresh without increasing Astra calls.
   Reveal the private view only if needed; it starts hidden.
3. Check detector status. An error or unavailable detector is a failed preview,
   not a successful zero-mask result. A public product page with no private data
   proves navigation only, not sensitive-data detection.
4. In the dedicated Edge window, press Ctrl+T and open a second ordinary website,
   such as `https://example.com/`. (The dashboard's URL button reuses the selected
   tab.) Select each managed tab and confirm the preview follows it. Scroll, reload or navigate
   in the visible browser and request a new preview. Close the managed browser
   only after the test; Stop Astra should leave manual browsing available.

## 2. Check private pixels locally

Use synthetic contact information on ordinary editable pages where available,
or user-led sign-in to inspect an account view. Do not make purchases or submit
account changes for this test. Compare the local raw view with the protected
preview. Inspect email, phone, names, multiline addresses and credential-like
text, including after scrolling or zooming. Record actual masks, misses and
detector timing. Do not infer protection from a token list alone. Do not start
cloud assistance if private content remains visible. Manual masks, if offered
by the integrated runtime, must be recorded as manual protection.

## 3. Inspect a live request

1. Configure the API key locally. Enter a benign task, for example: “Look at the
   current public page, then navigate to https://example.com/, report its visible
   heading, and finish. Do not submit forms or purchase anything.”
2. Choose Start live Astra. The latest preview is not proof of transmission.
   Open the outgoing-request inspector and select an actual recorded request.
3. Inspect its protected image, frame hash, masks/timing where supplied, status,
   and scrubbed text. This image should be the submitted frame, even if the latest
   preview subsequently changes.
   Submitted images come from the recorded payload, including follow-up tool
   outputs. A separately recorded image without a payload match stays unverified.
   If an evidence mismatch appears, do not treat the displayed runtime hash as
   verification of that payload image.
4. Confirm the returned provider response ID, returned model, usage and original
   sanitized actions. A prepared entry, missing receipt, failed request or fixture
   entry does not establish a successful live model response. Missing fields must
   remain unavailable; the viewer must not invent them.
5. Stop Astra and confirm the run stops while manual browsing remains usable.
   Inspect follow-up observations after navigation and tab changes too.
6. Download protected evidence JSON and inspect its requests. Keep raw screenshots,
   local tab metadata, credentials and resolved private values out of shared
   evidence. Export safety depends on the runtime's scrubbing boundary.

## 4. Regression and failure checks

- Use the explicitly labeled old fixture rehearsal separately. It uses marked
  synthetic fields and scripted actions, makes no model calls, and does not prove
  ordinary-site OCR or live Astra behavior.
- With the integration owner, force a detector failure. Confirm the UI shows the
  error and no new cloud request is sent. Never interpret an old protected image
  left on screen as a fresh successful preview.
- Disconnect the test runtime or return an API error. Confirm an actionable error
  appears and controls recover. A rejected run must not be shown as started.
- Leave the request inspector open while a prepared request transitions to a
  response without changing its step. The receipt must update.
- If capture reports recovery by bringing the selected browser tab to the
  foreground, expect that local focus change. It is capture recovery, not a model
  action or proof of a cloud request. Verify tab identity and the fresh preview.
- After a capture/detector error, automatic previews pause. Correct the local
  issue, select the intended tab and choose **Refresh preview**. Inspect the new
  image before restarting Astra. Any retained preview is stale evidence.
- **Stop Astra** requests cancellation; wait for the status to leave Working.
  It cannot retract a request already submitted. Inspect any returned receipt.
  **Close browser** is separate and closes the dedicated session.

Record browser/version, URLs, selected tab, detector/version, supported classes,
misses, frame hashes, real response IDs, timings and manual steps. Redact private
metadata before sharing. Amazon compatibility and multi-site privacy remain
unverified until these checks pass against actual pages and the integrated runtime.

## Session 4 verification scope

The viewer is tested against isolated mocked API responses to verify controls,
request payloads, local-preview versus sent-frame separation, receipt updates and
failure display. These UI checks do not call Astra and do not establish detector
accuracy, Amazon compatibility or backend export safety. Those require the
integration and independent browser acceptance sessions.

Session 4 result (2026-09-08): PASS using headless Microsoft Edge with Playwright,
static server bound to `127.0.0.1:18084`, and intercepted mock `/api/*` responses.
Verified open/select payloads, no model call for preview, raw image source absent
while hidden, prepared/missing-receipt labels, response update at unchanged step,
submitted hash distinct from preview hash, web/fixture run payloads, Stop keeping
tabs, detector-error blocking, no horizontal overflow at 390px, and no page script
errors. Desktop 1440px rendering was visually inspected. JavaScript syntax checks
passed for both `static/app.js` and `static/audit.js`. Audit-agent DOM checks also
covered sent/failed/legacy states and no polling with the inspector closed.

## Actual website evidence available at this revision

The independent [browser acceptance report](BROWSER-TEST-REPORT.md) records
successful synthetic-email pixel masking on actual HTTPBin and Selenium form
pages: 839 and 987 changed field pixels respectively were covered. These are
specific observed samples, not site-wide guarantees. The HTTPBin token follow-up
then failed authorization, and a later fresh OCR attempt failed exact recognition.
That report snapshot did not yet contain live provider receipts; the subsequent
public navigation run is reviewed below. Successful token insertion followed by
protected capture and repeatable two-site private-content coverage remain separate
acceptance items; the later token-run result below updates the initial pending
status. Mock IDs used in UI tests are never substitutes for real receipts.

Viewer follow-up checks (2026-09-08): JavaScript syntax and focused mocked DOM
checks passed for preview-hash rendering, error blocking, foreground-recovery
feedback, result-message preservation, and receipt image extraction from initial,
computer-screenshot and function-output payloads. Tests also checked image
mismatch warnings, image-only unverified records, uncertain failure and fixture
labels. These checks exercise display logic, not real provider acceptance.

## Actual live export review (2026-09-08)

The integration owner supplied the completed Amazon-to-example.com run as
operator-local `.plva-evidence/amazon-example-live.json`; it remains outside Git.
Session 4 independently read that export. Its SHA-256 is
`9ccbd86208a9d97464afe4475c134fd6ef19ffee15c2de21da9337dd11fafa93`.

Both entries report `responded`, HTTP 200 and returned model `gpt-6-astra`:

| Provider response ID | Input / output tokens | Protected PNG SHA-256 |
| --- | --- | --- |
| `resp_07744b585abea20e006aa093064f1c87d08ec4d2d80da4022a` | 2421 / 77 | `e4c257c26208bd3f1aa55f2ecdf8e73005567e45f35085dba86a65db5f9e333c` |
| `resp_07744b585abea20e006aa0932d7ce487d0855f4253ea211842` | 3898 / 58 | `80f3e01c743b36690326ec48fbebdb070def8a1fd888fe24ebe10b92bdd92d8c` |

For each entry, Session 4 decoded the actual payload image and the separately
recorded image and computed their SHA-256 hashes. Both matched the entry's
`frame_hash`; the two frames are distinct. Provider provenance comes from the
integration owner's actual run, not from receipt-shaped JSON alone. This review
checks the supplied record and image consistency; it does not independently
replay or authenticate the provider request.

An isolated headless Edge rendering of the actual export through `static/audit.js`
also passed: both response IDs and hashes appeared, exactly two payload images
rendered, no mismatch warning appeared, and there were no page-script errors.
The test replayed the saved export locally; it did not control the integration
browser/server or make another provider call.

This was a public-page navigation run, with no synthetic private-data challenge.
It establishes live request/response evidence and exact recorded-image matching,
not pixel-level private-data removal. The independent HTTPBin/Selenium pixel
samples above, their failed follow-ups, and remaining token/reliability checks
must be reported separately.

## Actual live token export review (2026-09-08)

The integration owner subsequently supplied
`.plva-evidence/httpbin-astra-token-live.json`, SHA-256
`a28365ea660f669ccfdf80c6e3cb910c9618d1eb6846ffcc6da41aacb8c635ae`.
Session 4 independently verified all five entries report HTTP 200, `responded`
and `gpt-6-astra`. Every decoded payload image matches its separately recorded
image and `frame_hash`. There are four distinct protected PNGs across five
requests; the first two requests use the same frame.

| Provider response ID | Protected PNG SHA-256 |
| --- | --- |
| `resp_048ab083d6339525006aa0940ac7ac87d0b9cd3c2c9de98152` | `2baa2fcd70b17cad83bb3992c083fbeaba43f6085eadb0710dc1dc2fbccb4bd9` |
| `resp_048ab083d6339525006aa0940fbe3487d0a864254d6694c42b` | `2baa2fcd70b17cad83bb3992c083fbeaba43f6085eadb0710dc1dc2fbccb4bd9` |
| `resp_048ab083d6339525006aa09414cca887d080a5c1bc868fb60d` | `23d24327fb723f748d643d5e1725d39278454d8708902203d79c76ed3b5abe06` |
| `resp_048ab083d6339525006aa0941b68cc87d0a581ed7321b50cbe` | `f5b144db62a1e6049b503237ac1de56dfec324f949f193367d19ffb778a8daff` |
| `resp_048ab083d6339525006aa0942057d487d086f8ee6fb737a428` | `db02e840d6eb7a1880d1491ca34ef524dd10d04b584bc26200c6981630955024` |

The integration owner reports the actual `run_astra_acceptance.py` workflow
passed: 845 initial email glyph pixels masked, one email token resolved locally
with exact field equality, then Astra scrolled and navigated to example.com and
returned the correct final answer. The owner checked plaintext synthetic-email
and API-key absence before export. Session 4's independent check is limited to
the supplied receipts and image hashes; it did not rerun those action/pixel oracles.

The combined script checks initial private pixels only. Session 5 separately
checked post-typing pixels; do not describe this export alone as a combined
post-typing pixel proof. Earlier failed samples remain reliability evidence.
Consult the current independent report for final cross-tab and two-site results.

## Fresh served-dashboard flow (2026-09-08, 23:10–23:12 UTC)

Session 4 exercised the actual `http://127.0.0.1:18080/?v=ready` dashboard through
CUA in its own in-app browser tab during the integration owner's explicit test
window. No API responses were mocked. The current UI includes the 10-second
cooldown after completed automatic previews. Main JavaScript syntax checks passed.

- **Open website:** entered `https://example.com/`; the selected managed tab and
  origin matched. Protected preview appeared, raw view stayed hidden, and model
  calls remained zero. Initial displayed detector time was 4239 ms.
- **Start live Astra:** requested the current heading without navigation/clicks.
  The run completed with “Example Domain” and one model call. The inspector showed
  HTTP 200, returned `gpt-6-astra`, usage 2373 input / 6 output tokens, no actions,
  and receipt `resp_0ed71687ef73b0de006aa095dd921887d0a104878ed4217655`.
  Actual submitted image and payload details rendered visibly; later local
  previews did not replace the request record.
- **Export:** clicked Download protected evidence JSON. The in-app download's
  file location was not exposed; the integration owner separately preserved the
  current export as `.plva-evidence/ui-flow-20260908T231117Z.json`. Session 4 checked
  its SHA-256 `44e83380b72ada723f819d909b5a0b02480415902f9caa764b12b7cdbe1d55f4`.
  Decoded payload and recorded image both matched frame hash
  `80f3e01c743b36690326ec48fbebdb070def8a1fd888fe24ebe10b92bdd92d8c`.
- **Stop:** a short second task completed before the Stop click; that attempt
  does not prove cancellation. A third benign navigation/scroll task was stopped
  immediately after Start. The UI showed “Stopped by operator,” zero model calls
  and the still-open managed tab. Close browser then showed closed/no tabs/no
  frame and disabled Start. The test tab was closed and the window released.

One Start and one Close attempt coincided with automatic-preview busy state;
retrying the enabled UI control succeeded. Recovery feedback appeared in Activity
when the managed page was brought forward. No UI code change was required.
This fresh test proves the observed served controls, live receipt display and
pre-send cancellation. It is not an additional private-pixel or multi-tab test.
