# PLVA: ordinary websites first, native desktop second

## Priority and definition of success

The user's first priority is: open Amazon or another ordinary website, and ensure
that the observations Astra receives pass through PLVA before leaving the machine.
The page must not need our HTML annotations, injected privacy labels, a modified
copy of the site, or a preloaded list of its private values.

Phase 1 delivers this in a PLVA-managed, visible browser on Windows. Both user
browsing and Astra-driven browsing must use that same browser session. It does not
silently intercept every browser or AI tool already running on the computer.
The UI must make that boundary clear: open the site through PLVA, browse normally,
and inspect the protected observation before enabling Astra.

Phase 2 adds native computer use after Phase 1 passes its acceptance checks.
This is the active execution plan and supersedes the earlier desktop-first order.
Keep the scope at hackathon scale: one dependable browser path, one local detector,
one outbound protection path, and an understandable viewer.

## Milestones, in priority order

1. **Private observation on ordinary websites.** Enter an Amazon URL or another
   HTTPS URL, open the real website, and show raw/local versus protected preview.
   Find supported private information locally from the screenshot. No model call
   is necessary for this first proof. Scrolling, navigating and changing tabs
   produce fresh observations.
2. **Verified protected input to Astra.** Send those protected observations to real
   Astra through one checked send path. Inspect exactly which image/text was sent
   and the provider's response ID. No alternate raw-image route.
3. **Useful multi-site agent work.** Astra follows a user task across two ordinary
   websites. Navigation, screenshots, local token use when needed, and subsequent
   observations all use the same protection path.
4. **Native desktop reuse.** Replace browser capture/input with Windows capture/
   input while retaining detection, vault, send path and viewer.

Do not hold milestone 1 behind native mouse control, desktop DPI work, Qwen,
NemoClaw, automatic skills, or a complete general-purpose policy framework.

## Starting code and required changes

| Existing piece | Keep | Change for Phase 1 |
| --- | --- | --- |
| Real Astra Responses integration | Provider connection and action format | General user tasks, protected send boundary and provider receipts |
| Playwright/Edge | Browser engine and action primitives | Visible persistent session, user-selected URLs, tab/navigation support |
| data-private discovery | Only as an explicitly labeled old regression fixture | Replace in normal mode with local screenshot OCR/classification |
| Local masks and vault | PNG masking, token storage and resolution | Connect image findings; support stable tokens across sites and pages |
| URL/field action gate | Local action checking principle | Remove localhost-only assumption; authorize user-selected sites and check the actual destination before token use |
| Replacement-form completion | Keep old smoke test | Check the outcome of the user's selected workflow |
| Dashboard/audit | Reuse layout and request inspector | URL entry, selected browser/tab, preview/send distinction, actual API receipts |

## Separate sessions and agents

These are five persistent Codex tasks, not five subagents inside one task. Each
lead owns its branch/worktree, subagents, validation and handoff. The current task
may serve as Session 1; create the other four when execution is requested.
Record real task IDs on a shared status board. Start from the current working
implementation, including required uncommitted files; keep .env out of commits.

| Session title | Larger goal | Subagents inside the session | File ownership |
| --- | --- | --- | --- |
| 1. PLVA Browser — Integration and Coordination | Deliver the protected browser-to-Astra loop | Contract/review agent; provider/history agent | plva/contracts.py, plva/runtime.py, plva/server.py, dependencies and integration status |
| 2. PLVA Browser — Real Websites and Navigation | Browse ordinary sites in a user-visible session | Browser-session/navigation agent; action/token-destination agent | plva/browser/, tests/test_browser*.py |
| 3. PLVA Browser — Local Screenshot Privacy | Detect and hide private content without changing websites | OCR/regions agent; classification/vault agent | plva/detection/, plva/privacy.py, detector/privacy tests |
| 4. PLVA Browser — Preview and Evidence Viewer | Let the user inspect what Astra receives | Preview/controls agent; audit/receipt agent | static/, docs/BROWSER-USER-TESTS.md |
| 5. PLVA Browser — Independent Verification | Prove privacy and usefulness across ordinary sites | Pixel/text privacy agent; live multi-site test agent | tests/browser_e2e/, docs/BROWSER-TEST-REPORT.md |

Queue work within the available agent capacity. Each session can spin up its named
subagents when slots permit. Do not assume all sessions and all children can run
simultaneously. Only one worker controls a given browser session; use separate
profiles for isolated tests and explicitly hand off the integration browser.

## Session 1: integration and outbound boundary

- Freeze small interfaces: browser capture -> PNG plus dimensions/tab identity;
  detector -> local findings; privacy -> protected PNG plus value-free manifest;
  executor -> checked actions with local token resolution.
- Have exactly one cloud send function. Every outgoing screenshot, including
  retained screenshots or crops if supported, must be protected. Scrub task text,
  observations, URLs/titles if included, errors and history before sending.
- Avoid cloud DOM dumps, clipboard reads, HTML or accessibility text as alternate
  observation channels. If an additional text channel is introduced, give it the
  same explicit local scrubbing boundary before enabling it.
- Keep resolved values in a local action copy; model history retains tokens.
- Preserve safe provider history only. Do not retain an earlier unprotected frame
  just because a later frame was redacted.
- Record actual protected payload, image hash, send/result status, provider response
  ID, returned model and token usage. Never include authorization headers.
- Integrate the ordinary-browser route separately from the old prepared fixture.
- Stop the cloud send if capture/detection/redaction fails. Surface the actual
  failure; do not fall back to raw screenshots.

Exit: real Astra receives a protected observation from an unmodified website and
its returned action executes in the same browser session.

## Session 2: ordinary websites and user browsing

- Replace the hard-coded support URL with a URL input and user-visible Edge session.
- Support user navigation and agent navigation, back/forward, scrolling, reload and
  tab selection. Capture the correct tab after navigation and before the next send.
- Use a dedicated local browser profile for this demo. Allow the user to sign in
  directly there if they want account-page testing; do not copy their unrelated
  browser profile or ask them to paste credentials into chat.
- Show the active origin and whether Astra is paused. Provide local-only preview
  while the user browses, with a clear separate control to start cloud assistance.
- Keep the detector screenshot-based. Generic browser focus/input metadata can
  help the local executor authorize typing; it must not become a hidden source
  of private values for the detector or cloud model.
- Replace the annotated-field token check with a small destination rule: actual
  active origin, focused editable element and permitted token class. If ambiguous,
  pause for a local user choice. Do not resolve private tokens into URLs or search
  boxes simply because the model proposed it.
- Preserve stop/cancellation. Handle popups and tab changes explicitly.
- Treat site login, CAPTCHA or anti-automation barriers as visible manual steps or
  limitations. Do not promise Amazon compatibility until tested on its actual page.

Exit: the user can open Amazon and a second ordinary site, browse and switch tabs,
and receive protected previews without website modifications.

## Session 3: local image detection

- Read the reference OCR/findings pipeline and reuse portable pieces where useful.
  Select one available Windows-local OCR path and verify its model files and CPU
  inference before expanding implementation. Do not import Apple-only dependencies.
- Input is screenshot PNG bytes. Output is recognized text, sensitive value spans,
  screen rectangles and confidence, all kept local before masking.
- Cover demo classes: email, phone, name, address and obvious credential patterns.
  Use text patterns for structured secrets and visible context/local classification
  for names and addresses. State exactly what is supported and what is missed.
- Do not hard-code Amazon selectors, customer values, test URLs, or screen positions.
  Visible labels are allowed contextual evidence; invisible privacy annotations are
  not part of the production detection route.
- Test unknown synthetic values, multiline addresses, small text, scrolling, zoom
  and different layouts. Map OCR coordinates correctly back to screenshot pixels.
- Reuse known vault values to help find later appearances after initial discovery.
- Keep passwords and blocked secrets masked; demonstrate usable tokens first with
  synthetic contact data rather than a real purchase or account change.
- If an operator region mask is offered as a fallback, label it manual protection.
  It is useful, but cannot count as automatic-detection acceptance.

Exit: image-only detection works on multiple independent layouts with values not
supplied to the detector ahead of time; later occurrences remain protected.

## Session 4: visible proof for the user

- Reuse the web dashboard; add URL entry, open/select tab, live local preview,
  Start Astra, pause/stop, and clearly labeled scripted fixture mode.
- Raw pixels are operator-only. The active content tab is the capture source;
  never capture the dashboard's raw preview and send it back through the agent.
- Distinguish latest preview, image actually sent, and provider response. An idle
  preview must not be labeled as a cloud request.
- Show frame identity/hash, masks and processing time beside the actual sent image.
- Display provider response ID, returned model, usage and sanitized original
  actions so the user can distinguish real model behavior from a script.
- Export protected evidence and write a short user test guide for Amazon plus a
  second site. State that the dedicated PLVA browser is the protected session.

Exit: the user can inspect a site before sending, run Astra, and see verifiable
request/response evidence without reading source code.

## Session 5: independent browser acceptance

Test in this order:

1. Run synthetic screenshot tests independent of site annotations. Check pixels,
   not just strings in JSON. Include fresh values and layouts.
2. Open the actual Amazon site in the managed browser. Verify browsing, tab identity
   and local preview. A public product page containing no PII proves navigation,
   not private-data detection. Record that distinction.
3. Exercise visible private content on at least two unmodified website origins.
   Prefer synthetic data entered into ordinary editable fields. A local test page
   can supplement tests but cannot be the only evidence. Use user-led sign-in for
   account views only if needed; do not purchase or submit account changes as tests.
4. Inspect protected images locally first, then run real Astra on a benign multi-site
   task. Verify actual provider receipts and that every sent image/text passed the
   protection path, including after scroll, navigation, typing and tab changes.
5. Verify tokens resolve locally into an intended test field and that the next
   screenshot hides the entered value. Check unknown/blocked tokens and stop.
6. Force detector failure and verify that observation produces no cloud request.
7. Test a new value/layout and document actual supported classes, misses, timings,
   site barriers, and manual steps. Do not label untested websites fully protected.

Exit: an honest evidence report proves real-site navigation, private-data masking,
live Astra use and protected follow-up observations beyond the prepared fixture.

## Scheduling and status

Session 1 freezes contracts first. Sessions 2 and 3 then build in parallel;
Session 4 consumes agreed preview/audit data; Session 5 prepares independent tests.
Integrate milestone 1 before adding general task polish. Complete milestones 2
and 3, then run the acceptance tests and deliver user instructions.

At dispatch, Session 1 creates docs/BROWSER-STATUS.md with one row per session:
actual task ID, branch/worktree, named active agents, state, next deliverable,
test evidence, blockers and browser ownership. The session lead reports changed
files, commands/results and limitations. Session 1 is the board's single writer.

States: planned, running, ready for integration, verifying, complete, blocked.
Do not mark the multi-site feature done because the old replacement form passed.

## Phase 2: native computer use

Begin after browser milestones pass. Follow DESKTOP-MULTI-SESSION-PLAN.md for the
remaining Windows capture/input, DPI, foreground focus, operator-view exclusion,
native-app switching and saved-output verification work. Reuse the detector,
vault, scrubber, provider boundary and evidence viewer from Phase 1. Do not rerun
completed browser work as a new desktop implementation.

Qwen/NemoClaw and screenshot-to-skill remain separate teammate workstreams. They
can continue independently, but neither blocks protecting ordinary browser pages.

## Current status

Execution started: four separate implementation tasks, each with two subagents,
plus the current integration task. See docs/BROWSER-STATUS.md for current evidence,
handoffs and remaining acceptance gates. Do not infer live real-site readiness
from the original prepared-page demo or from this plan alone.
