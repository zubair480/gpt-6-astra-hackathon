# Fresh flow test — September 8, 2026

Result: the tested Windows browser flow passed. This run exercised the actual
dashboard, real public websites, local OCR/masking/token entry, and real Astra.

| Check | Fresh result |
| --- | --- |
| Default suite | 122 tests: 108 passed, 14 explicit opt-in skips, no failures; 46.431 seconds |
| Real-site privacy suite | 3 passed, no skips/failures; 33.403 seconds |
| Actual dashboard | Open → local preview with zero calls → Start live Astra → correct Example Domain answer and real receipt |
| Dashboard Stop/Close | Immediate Stop on a longer task prevented all model calls and left browsing available; Close removed tabs/frame and disabled Start |
| Real Astra token workflow | 6 successful API responses, 4 distinct protected frames, 1 exact local email-token insertion, executed scroll and navigation to example.com |
| Actual submitted post-type pixels | All 880 initial email glyph pixels checked again after typing, before scrolling; matching protected frame linked to later successful requests |

## What was fixed

The first fresh suite found a Windows startup race: Edge's DevToolsActivePort
file existed but was temporarily locked by its writer. Browser startup now retries
missing/locked reads within the existing 15-second startup budget. It does not
relaunch Edge or hide unrelated I/O errors. Five new regression tests cover the
lock, partial file, deadline, process exit and unrelated errors. The full suite
above passed after this change. The app was restarted with the fix.

The live verification script now checks the complete initial private glyph set
against actual post-type screenshot pixels, requires EMAIL-mask coverage and
changed protected pixels, and checks the active tab. A proof must match a
successful request sent after the check; an identical earlier frame cannot count.
Actual executor returns establish that scrolling/navigation executed.

Two stricter attempts stopped because this glyph comparison was also being
applied after scrolling. The retained failed run shows successful post-type
checks and two later matching responses before the post-scroll assertion failed.
The combined test now explicitly checks the post-type/pre-scroll checkpoint.
Scrolling retains its separate moved-field pixel test. Screenshot/geometry timing
is a possible explanation for the failed comparison, not an established cause.
The failed verdict remains recorded; no private-glyph assertion was relaxed.

## Actual evidence

Protected exports remain local and Git-ignored in `.plva-evidence/`; previous
exports were preserved. New exports use timestamped names.

- Dashboard: `ui-flow-20260908T231117Z.json`.
  SHA-256 `44e83380b72ada723f819d909b5a0b02480415902f9caa764b12b7cdbe1d55f4`.
  Actual response `resp_0ed71687ef73b0de006aa095dd921887d0a104878ed4217655`.
  Returned model `gpt-6-astra`, HTTP 200; protected payload/recorded-image hash
  `80f3e01c743b36690326ec48fbebdb070def8a1fd888fe24ebe10b92bdd92d8c`.
- Fresh token flow: `httpbin-astra-token-live-20260908T231639171676Z.json`.
  SHA-256 `fac159c3700073f096d1b22c1f1fcbc7a2f8ab89ed4bbeb773a004f921c0b0a9`.
  Post-type protected PNG hash
  `133cc96672d4a9291d7f89feeb9b52b37265db4306209cc4113526509a38306a`.
  It matched successful zero-based request indices 2 and 3, with responses
  `resp_08e2d913eaf9c5fd006aa09746c6e087d0b7a49efec55a2bdd` and
  `resp_08e2d913eaf9c5fd006aa097495f5887d082c2213d50d684d2`.
  The local verifier checked that the inserted value equaled its fresh email
  oracle and that plaintext email/API key were absent from exported text.
- Retained failed attempt:
  `httpbin-astra-token-failed-20260908T231500696567Z.json`.
  Its protected requests/actions and fixed error explain the checkpoint issue.
  The earlier failed attempt did not retain an export and is not counted as a pass.

The fresh real-site tests independently checked HTTPBin email (832 glyph pixels),
phone (443), and Selenium email (1008). The transition test checked 847 email pixels
before/after actual scroll, navigation to another origin, return to the first tab,
and capture after Stop. All reported zero uncovered or retained private glyph pixels.

## Reproduce

```powershell
python -m unittest discover -s tests -q
$env:PLVA_RUN_LIVE_PRIVACY = '1'
python -m unittest tests.browser_e2e.test_live_privacy -q
python -m tests.browser_e2e.run_astra_acceptance
```

The last command uses the configured real Astra API key and saves a new protected
export. Run browser/OCR checks serially on this machine. The actual dashboard
workflow is described in [BROWSER-USER-TESTS.md](BROWSER-USER-TESTS.md).

## Scope

This is the dedicated Windows browser demo. OCR can still miss or overmask text;
tested samples do not certify every account page, website or private-data class.
Failure-path provider tests use mocked transport; the listed successful Astra
responses and dashboard Stop check used the live runtime. The first short Stop
attempt finished before the click and was not counted as cancellation proof.
Native desktop, Qwen/NemoClaw and skill learning remain separate work.
