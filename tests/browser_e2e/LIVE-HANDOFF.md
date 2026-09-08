# Coordinator-owned live browser acceptance handoff

These steps are pending integration verification, not recorded passes. The
automated `test_live_sites.py` tests prove only navigation/capture contracts;
even a successful Amazon check can show a CAPTCHA instead of usable content.
No private values are entered by these tests. No provider calls are made.

## Ownership and setup

Request an explicit test window from coordinator task
`01a082f1-d26d-78e2-946d-87abf4bca5dc` before using its browser or server. The
coordinator should perform these steps or hand over exclusive control. Do not
launch another process on port 18080. Isolated automation uses a fresh temporary
profile through an explicit BrowserSession constructor option and never copies
an existing browser profile. Current contract does not specify that option's
name; the test skips explicitly if none of the supported explicit options exists.

Dependencies: integrated `plva.browser.BrowserSession`, local browser engine and
its runtime dependency, integrated `plva.detection.ScreenshotDetector` and local
OCR assets, Pillow, integrated protected runtime and audit endpoints. Real Astra
verification additionally requires the coordinator's configured provider; do not
read/copy `.env`, record headers, or include credentials in evidence.

Run navigation separately:

```powershell
$env:PLVA_RUN_LIVE_BROWSER = '1'
python -m unittest discover -s tests/browser_e2e -p test_live_sites.py -v
Remove-Item Env:PLVA_RUN_LIVE_BROWSER
```

Disabled tests, missing components, navigation barriers, and absent provider
configuration are skips/blockers, never acceptance passes. Enabled tests fail on
unexpected browser dependency errors or contract mismatches. They retain no raw
captures on disk. Record command, date, OS/browser version, observed barriers,
and pass/fail/skip counts in `docs/BROWSER-TEST-REPORT.md`.

## Two-origin visible-data proof

1. With Astra paused, open `https://httpbin.org/forms/post` in the dedicated PLVA
   browser. Locally generate a fresh name, email under `example.com`, and phone
   in the fictional `202-555-0100` through `202-555-0199` range. Keep the generated
   values in the verifier only; do not pre-register them in the vault/detector.
   Enter them visibly into the corresponding fields without submitting. Public
   sites may observe field input; therefore use only synthetic values.
2. Request local preview. Record origin, tab ID, capture dimensions, processing
   time, and manifest. Verify each visible value has an appropriate mask in the
   actual protected PNG. Compare source glyph pixels against the masked region,
   not only JSON strings or a nonzero mask count. Verify all visible source glyphs
   are covered and rerun independent OCR/visual review on the protected PNG.
   Record missed names/phones explicitly even if email succeeds.
3. Open `https://www.selenium.dev/selenium/web/web-form.html` as the second origin.
   Enter a different fresh email and multiline synthetic postal address in the
   visible textarea, and a synthetic name in the text field; do not submit.
   This site's generic labels intentionally test whether detection generalizes.
   No HTML changes, privacy annotations, custom CSS, or detector hints are allowed.
   Repeat pixel inspection. A miss is a failed class/layout acceptance case.
4. Scroll and change zoom using ordinary browser controls, switch between tabs,
   and capture again. Verify mask coordinates against screenshot pixels after
   each change. If BrowserSession does not offer new-tab control, navigate between
   origins and document tab switching as unverified until manual tab creation.
5. Separately open `https://www.amazon.com/`. Record actual page or barrier and
   correct active tab/source preview. Public navigation without private content
   establishes no Amazon private-data-detection claim.

## Provider boundary and useful follow-up task

After local pixel verification passes, ask Astra for a benign task: inspect both
open form pages, describe their non-private controls, and scroll each to inspect
remaining controls, without submission. Do not put raw synthetic contact values
in the task. Retain a verifier-only list for assertions against *every outbound
text field*: task, title/URL, history, tool output, errors, and action summaries.

For every actual send record request ID, protected PNG SHA-256, status transitions,
provider response ID, returned model, usage, and token-only action summaries.
Decode every outgoing image, including retained history images/crops, and inspect
its masks. Match bytes/hash to the audited sent image. A prepared preview or a
fabricated/mock receipt does not demonstrate a provider call. Record actual
multi-site actions and whether useful task completion occurred.

Exercise one allowed email token into a visibly focused intended email field,
through the local execution gate. Check the value appears only locally, that
history retains its token, and that the next sent frame masks it. Attempt an
unknown token, a secret token, a wrong-origin target, and a search/URL field;
verify rejection before resolving/inserting. Do not attempt real purchases,
account changes, credentials, form submissions, or CAPTCHA bypass.

## Failure and stop checks

Through an isolated runtime test hook, force detector inference to raise after
capture. Count provider calls before/after and require zero additional sends;
verify an operator-visible error, no raw fallback, and no successful empty result.
Repeat for capture and redaction failures. Restore hooks before continuing.

Press Stop while a request is pending and verify no subsequent action or cloud
send occurs. A request already in flight may return; record that distinction.
Verify manual preview/navigation remains usable while paused. Close explicitly
when finished and return ownership to the coordinator.

Report each case as passed, failed, skipped, or blocked, with supporting frame
hash/request ID and specific limitation. Keep raw screenshots/values local;
export only reviewed protected artifacts. Never generalize two tested pages to
all sites or all private-data classes.
