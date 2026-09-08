# Managed browser boundary

`BrowserSession` owns a dedicated local Edge profile and defaults to a visible
window. It does not attach to personal browser profiles or the coordinator's
browser. All methods run on the same owning asyncio event loop.

The integration sequence is `start()`, `open(https_url)`, `capture()`, local
screenshot detection, privacy masking, and only then a checked cloud send.
`capture()` returns PNG bytes, image dimensions, tab ID, URL and title. The URL
and title are local metadata: the integration must scrub them before cloud
transmission or evidence export. Browser code does not read page text for
privacy detection and does not make cloud requests.

`tabs()` lists local tabs and `select_tab(tab_id)` brings the selected tab forward.
`execute(action, privacy)` performs supported computer or navigation actions.
It returns a value-free execution summary. Private token values are resolved
only locally after destination checks. A refused destination requires a local
operator decision; the agent cannot grant itself permission to type private
values into another origin. `close()` closes this session only.

Browser navigation is not privacy-detection acceptance. Public pages with no
private information only demonstrate capture, navigation and tab identity.
Login, CAPTCHA and anti-automation barriers remain visible manual steps. No
CAPTCHA bypass, purchases, account changes or credential automation are tests.

Constructor options are keyword-only: `profile_dir`, `headless=False`,
`channel='msedge'`, `viewport` (default 1200x900), `allow_loopback_http=False`,
`stop_check` (synchronous callback that may raise `InterruptedError`), and
`navigation_timeout_ms=30000`, and `capture_timeout_ms=5000`. Screenshot attachment
and capture each use the separate five-second bound so a stalled screenshot can
reach the existing foreground retry without waiting for the navigation timeout.
The default profile is
`%LOCALAPPDATA%/PLVA/BrowserProfile`. Use a unique temporary `profile_dir` for tests.
No test connects to the integration server on port 18080.

The session launches its own Edge process with an ephemeral local debugging
port, then attaches with Playwright's default emulation disabled. Ordinary
Playwright launch enables focus emulation for every tab; that would hide real
operator tab changes from the browser's focus/visibility metadata. This launch
path preserves actual tab state. Debugging transport stays on this machine.
Extensions are disabled in this dedicated browser. A real HTTPBin token test
found machine-installed extension onboarding tabs taking focus in a fresh
profile; the destination guard correctly refused entry on the unrelated origin.
The extension isolation change requires a browser restart.
Startup polls the local debugging endpoint for up to 150 attempts at 100ms
intervals. Missing or briefly locked endpoint files are retried within that
budget: a fresh full-suite run exposed Windows denying a read while Edge wrote
the file. Other I/O errors and browser exits still fail immediately. Five
startup regression tests passed, including persistent-lock exhaustion.
Viewport capture uses the page's CDP compositor surface rather than Playwright's
animation/font preparation, which can stall when the operator covers or minimizes
Edge. Browser background rendering flags keep local preview usable behind the
dashboard. Captures retain before/after tab and navigation checks and normalize
image dimensions to CSS viewport coordinates before local detection.
If the compositor still times out or refuses capture, PLVA brings the already
selected page forward and retries once. This may bring Edge in front of the
dashboard. It does not change the selected tab; a concurrent tab/navigation
change invalidates the attempt. Successful recovery returns
`capture_recovery='foreground'` for the integration to display. Failed capture
still produces no frame and no raw fallback.

Failures include fixed stage/reason codes such as `[capture.timeout]` or
`[image.failed]`. `last_capture_diagnostics` contains only status, stage, reason,
an allowlisted exception type, elapsed milliseconds and foreground-retry state;
it excludes driver messages, page text and URLs. Ten focused diagnostics and
recovery unit tests pass, including no retry on corrupt image data and no
foreground activation of a tab the operator has switched away from. The two
timeout tests cancel actual stalled coroutines for attachment and capture while
leaving the navigation timeout unchanged (10 tests passed in 0.847 seconds).
The opt-in persistent-loop regression
`PLVA_BROWSER_LIVE=1 python -m unittest discover -s tests -p test_browser_persistent_capture.py -v`
passed one test with five actual Amazon captures in 37.396 seconds. It mirrors
the runtime's caller-created Proactor loop and background daemon thread,
submits separate serialized requests, offloads simulated local image processing,
covers Edge with a separate owned window and restores it. The intermittent
integration capture error was not reproduced; this is browser lifecycle evidence,
not an actual OCR/provider end-to-end acceptance result.

`open(url, new_tab=True)` creates a tab; plain `open(url)` navigates the active tab.
Only operator `open()` authorizes the requested origin for token entry; a redirect
does not authorize its destination. Agent `execute({'type':'navigate','url':...},
privacy)` navigates without adding destination authority. The execution summary
contains `type`, `status`, `resolved` and `resolved_token_count`. The last two
fields contain the same integer for integration convenience.

Token typing supports editable input elements of type text, email and tel with
standard contact autocomplete semantics or email/tel input types. It checks the
current origin, selected-tab visibility, focused element and form destination,
then rechecks the exact element and metadata during insertion. Search fields,
URL fields, passwords, GET forms, cross-origin forms, secrets and ambiguous
destinations fail closed. Textareas, contenteditable fields and iframe contact
fields require local operator handling. This is a small destination rule for
ordinary sites, not protection against a malicious page controlling its own
JavaScript after receiving an authorized value. The browser exposes no cloud
JavaScript/DOM evaluation action.

Pausing stops agent actions through `stop_check`; local browsing, opening tabs,
preview capture and close remain available. The integration should serialize
operations and check its stop flag between actions. Manual tab selection is
detected through visibility/focus metadata; capture retries a tab/navigation
race once, then refuses the frame. Persistent browser profiles can retain login
state locally, so operators should use this dedicated profile intentionally.

Validation on Windows with installed Microsoft Edge (2026-09-08):

- The independent verifier's HTTPBin retry after extension isolation passed in
  **17.918 seconds**: the authorized tab remained selected, exact email token
  insertion succeeded, and actual next-frame glyph masking passed. Phone
  detection/masking and unknown/secret-token rejection also passed. This is
  sample-specific evidence; the earlier random small-field detection miss remains
  a recorded reliability limitation. See `docs/BROWSER-TEST-REPORT.md` for current
  cross-origin and provider evidence, which is owned by the integration verifier.
- After disabling extensions and separating the capture timeout, the focused
  minimized/scroll/restore/manual-tab regression passed **2 tests in 18.019
  seconds**. A coordinator run under mixed CPU load previously failed the first
  test; that failure was not reproduced in this focused rerun, and no traceback
  established that it shared the extension-onboarding cause. Visible capture
  tests now require `PLVA_RUN_BROWSER_TESTS=1` to avoid interrupting other runs.
- Final combined suite: **23 tests passed in 65.083 seconds**, with both
  `PLVA_BROWSER_LIVE=1` and `PLVA_RUN_BROWSER_TESTS=1`. No skips or failures.
  Tested against the existing pinned Playwright 1.62.0 and Pillow dependencies.
- Follow-up occlusion regression: **2 tests passed in 12.738 seconds**. Verified
  exact scrolled pixels, fresh content changed while minimized, restoration and
  external tab switching. The original Playwright screenshot path timed out at
  its bounded 1.5-second timeout; the compositor path completed. The eight
  existing session tests also passed after this change (128.829 seconds under
  host contention). Set `PLVA_RUN_BROWSER_TESTS=1` and run `python -m unittest discover -s tests -p
  test_browser_capture.py -v` for the focused regression.

- Real public navigation: `https://www.amazon.com/` and `https://example.com/`
  loaded in visible managed Edge using a fresh temporary profile. Captures were
  1200x900 PNGs, distinct tab IDs, and tab switching/scroll/capture succeeded.
  Amazon showed a **Continue shopping** gate; it was not clicked or bypassed.
  Example Domain displayed normally. No sign-in, purchase, or account change.
- A separate CUA in-app-browser inspection showed the same Amazon gate and a
  normal Example Domain page. CUA Edge attachment was unavailable, so that
  inspection is separate from the application's successful Edge tests.
- A local routed synthetic HTTPS fixture verified actual token input and input
  events, denied search-field input, back/forward/reload and popup capture.
  These tests do not claim screenshot-detector or cloud-send acceptance.

Run browser tests from the project root with existing Playwright and Pillow
dependencies and installed Edge:

```powershell
python -m unittest discover -s tests -p 'test_browser*.py' -v
$env:PLVA_BROWSER_LIVE='1'
python -m unittest discover -s tests -p test_browser_live.py -v
$env:PLVA_RUN_BROWSER_TESTS='1'
python -m unittest discover -s tests -p test_browser_actions.py -v
```

To repeat the complete validated run, set both environment variables to `1`
and run the first command. The default suite includes isolated local Edge tests;
the environment variables additionally enable public network navigation and the
visible token fixture.

The live public test prints a local evidence directory containing the two
screenshots and `navigation.json` (URLs, titles, tab IDs, dimensions and hashes).
Do not publish raw captures from a signed-in profile. Test profiles are closed
and cleaned up; public screenshot evidence stays in the temporary directory and
is not committed.
