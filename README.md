# PLVA — hackathon demo

The [working Cloudflare application](https://plva-app.zubairzafar480.workers.dev/) connects this Windows runtime to a private web workspace. See [web-app/README.md](web-app/README.md) for access, connector setup, and deployment. The [four-click presentation](https://plva-demo.zubairzafar480.workers.dev/) is a separate scripted walkthrough.

Next implementation priority: [ordinary websites first, native desktop second](BROWSER-FIRST-MULTI-SESSION-PLAN.md).
The app now opens ordinary websites in a dedicated, visible Edge browser on Windows.

A Windows browser demo of private computer use: protect a screenshot locally, send
placeholder tokens to Astra, resolve them only while typing into matching fields,
and mask the filled form and receipt again.

## Run on Windows

Requires Python 3.12+ and Microsoft Edge. From PowerShell:

```powershell
.\start.ps1
```

First setup installs requirements and provisions pinned English OCR assets over
the network. Screenshot OCR then runs locally on the CPU.

Open http://127.0.0.1:18080. Enter a website URL, choose **Open website**, and
inspect the protected preview. Open, tab selection, and preview do not call Astra.
Browse in the dedicated Edge window; refresh the preview after changing its page.
Only this managed browser is in scope.

For live computer use, expand **Astra connection**, enter your hackathon API key
locally, save, enter your task, and select **Start live Astra**. Alternatively set `OPENAI_API_KEY`
before starting the server. Keys stay in process memory; restarting clears keys
entered through the UI. The provider adapter targets `gpt-6-astra` through the
Responses API's native `computer` tool.

## Ordinary website demo

1. Open Amazon or another HTTPS site through PLVA.
2. Inspect locally detected masks. The original screenshot is available locally
   when you enable its preview; it is not a model input.
3. Start a benign Astra task, such as describing the current page and navigating
   to example.com to report its heading.
4. Inspect each actual request's protected PNG, frame hash, returned model,
   response ID, usage and actions. Navigation and later screenshots use PLVA too.
5. Stop Astra to pause work; close the browser to end the privacy session.

The collapsed **Old fixture rehearsal** exercises the original prepared workflow
below. It is scripted and makes zero model calls.

## Original prepared workflow

1. The support ticket shows synthetic customer details and an irrelevant fake key.
2. The operator sees the original screenshot alongside the protected screenshot.
3. The agent copies tokens such as `[EMAIL_1]` into the replacement form.
4. PLVA substitutes the actual value locally, in the matching private input.
5. The receiver checks all six submitted fields; the resulting receipt is masked.
6. Inspect outgoing requests to see the actual sanitized request bodies and images.

The latest protected frame may be newer than the most recent cloud request. The
request inspector is the definitive record of what was submitted. Rehearsal entries
are explicitly marked not transmitted.

## Deliberate scope

Ordinary-site mode detects supported email, phone, name, address and credential
patterns from screenshot pixels using local OCR. It does not need website
annotations or a preloaded list of customer values. Names and addresses depend on
recognizable English context; small, clipped or unusual text can be missed.
Context rules can also mask non-private labels; this was observed on a form.
This is a hackathon detector, not a promise to find every private value on every
website. Inspect the preview before sending. See the current evidence and limits
in [the test report](docs/BROWSER-TEST-REPORT.md).

Private tokens resolve only inside local typing actions at approved destinations.
Secrets, unknown tokens and ambiguous destinations are blocked. Website access
gates may require a manual step. Native desktop control is the next phase.
The old prepared fixture alone still uses `data-private` annotations. Its sample
API key is fake and blocked; its contact tokens are usable. DOM dumps and original
screenshots are not included in ordinary-site model requests.

Qwen/NemoClaw and automatic skill synthesis are independent teammate workstreams.
There is no required Docker, WSL, NVIDIA, or Apple dependency. Protected evidence
can be downloaded from `/api/export`; this small demo schema is a starting point
for the teammate adapter, not a claim of completed skill integration.

## Files and checks

Current ordinary-site evidence: a real Astra run completed Amazon → example.com
in two API responses. A second run used a fresh synthetic email on HTTPBin,
resolved its token locally, scrolled and navigated to example.com in five real
responses. Independent real-site tests checked email/phone masking, the next
typed frame, scrolling and tab transitions. See the
[status board](docs/BROWSER-STATUS.md) and [operator guide](docs/BROWSER-USER-TESTS.md).
The latest [fresh flow test](docs/FLOW-TEST-REPORT.md) includes the Windows startup
fix and a six-response live rerun with submitted post-type pixel verification.

- `plva/privacy.py`: screenshot masking, memory-only values, tokens and scrubbing.
- `plva/browser/`: managed Edge capture, navigation, tabs and local action gates.
- `plva/detection/`: local screenshot OCR, classification and model provisioning.
- `plva/web_runtime.py`: ordinary-site observation, actions and stop handling.
- `plva/provider.py`: protected Astra payloads and provider receipts.
- `plva/runtime.py`: original prepared-fixture regression workflow.
- `plva/server.py`: local operator API, receipt receiver and evidence export.
- `static/`: viewer and sample workflow.

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
```

Historical prepared-fixture verification on September 8, 2026: 12 tests passed and a live `gpt-6-astra`
run completed in four API calls. Four private tokens were resolved locally; the
receiver verified all six submitted fields. Outgoing JSON records contained no
plaintext fixture values or API key. Screenshot masking is covered by pixel tests;
this is not a claim of general PII detection beyond the annotated demo fields.

No real shipment is purchased or sent. Live Astra requires an API key with access
to the hackathon model. The server loads `OPENAI_API_KEY` from the environment or
the Git-ignored local `.env` file.
