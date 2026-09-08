# Browser independent acceptance report

Date: 2026-09-08. Session 5 branch `codex/browser-independent-verification`.
Worktree: `C:/Users/aliam/.codex/worktrees/e723/gpt-6-astra-hackathon`.

## Current result

**Fresh strengthened live verification (23:16 UTC): PASS.** The coordinator's
timestamped export `httpbin-astra-token-live-20260908T231639171676Z.json` has SHA-256
`fac159c3700073f096d1b22c1f1fcbc7a2f8ab89ed4bbeb773a004f921c0b0a9`.
Session 5 independently verified all **6 HTTP 200 receipts, 4 distinct PNGs**,
exact outbound image/hash correspondence and complete response/tool-result chain.
The live oracle checked **880 original glyph pixels after exact token entry**;
the checked hash `133cc96672d4a9291d7f89feeb9b52b37265db4306209cc4113526509a38306a`
is tied to subsequently responded requests at indices 2 and 3:

- `e41e1465-2920-47c3-a6d5-6f8f7f6de07d` /
  `resp_08e2d913eaf9c5fd006aa09746c6e087d0b7a49efec55a2bdd`
- `d1670574-1c1f-47a2-a658-0c2960984b47` /
  `resp_08e2d913eaf9c5fd006aa097495f5887d082c2213d50d684d2`

Each request index is at or after its check's recorded audit boundary, so an
earlier identical masked frame cannot count as later submission. Captured tab 1
matches the original form. One local resolution and successfully returned type,
scroll and navigate actions are recorded. The strict pixel hook is explicitly
post-type/pre-scroll; separate moved-field tests establish scroll behavior.
An earlier strengthened run failed a later after-scroll pixel/geometry comparison
after its post-type checks had passed. That failed export is preserved; timing
was suspected, not treated as a confirmed privacy leak or erased from history.
The final hook scope retains every original glyph and the temporal send proof.

**Browser demo acceptance passed for the recorded samples, including real-site
token handling, live Astra and protected tab/scroll followups.** All results below
are bounded to the tested samples. Prior failures remain recorded under History.

| Acceptance gate | Current evidence | Verdict |
| --- | --- | --- |
| PNG-only unknown synthetic values | Unchanged five-class, small-email and multiline-address suite: 10/10 passed with English OCR `9689c55` | Passed for samples |
| Two ordinary origins, visible private content | HTTPBin email and Selenium public-form email: exact recognition plus changed source pixels masked, no site modifications/submissions | Passed for samples |
| Real local token entry + next frame | HTTPBin fresh email resolved at actual same-origin email field; local input equality, unchanged token action, strict next-frame glyph check; phone masking and blocked-token rejection | Passed |
| Actual Astra public navigation | Coordinator ran Amazon to Example Domain; Session 5 independently matched two HTTP 200 receipts, exact PNG hashes and response/tool chain | Passed; no PII claim |
| Actual Astra with synthetic PII/token/scroll | Fresh six-response run: exact token entry and 880 post-type glyphs linked to later actual requests; successful scroll/navigation; independent hash/chain review | Passed, with scope above |
| Same-session two-origin scroll/navigation/tab pixel checks | Full glyph checks passed after actual scroll, second site/tab, navigation, return and Stop | Passed |
| Failure and stop prevent sends/actions | Five isolated tests against production WebRuntime, including actual detector/protection failure wiring; real browser Stop blocked typing | Passed; provider failures use mocked transport |
| General OCR reliability | One historical fresh native-input email miss remains unexplained; no failure artifact was retained at that time | Limitation |

Session 5 never controlled the coordinator's localhost:18080 browser/server, read
credentials, submitted a form, or made purchases/account changes. Its live browsers
used fresh temporary profiles; live provider transport was performed by the
coordinator. DOM access in verification only sets/checks synthetic inputs and
measures geometry; detectors receive only PNG bytes. Raw failure artifacts stay
in local temporary directories outside git and are never sent to a provider.

## Reproduce

Install project requirements, then explicitly provision local OCR once:

```powershell
python -m pip install -r requirements.txt
python -m plva.detection.provision
```

Provisioning downloads pinned, hash-verified English recognizer assets; inference
never downloads models. Edge is required. Dedicated browser code `5e48839` disables
extensions and uses a 5-second capture timeout. Do not copy a personal browser
profile. Only one session should run browser/OCR-heavy tests at a time.

```powershell
python -m unittest discover -s tests/browser_e2e -p test_pixel_privacy.py -v
python -m unittest discover -s tests/browser_e2e -p test_pixel_oracle.py -v
python -m unittest discover -s tests/browser_e2e -p test_provider_receipt_check.py -v
python -m unittest discover -s tests/browser_e2e -p test_web_runtime_boundary.py -v
```

Real websites, with an explicitly assigned isolated browser/CPU window:

```powershell
$env:PLVA_RUN_LIVE_PRIVACY = '1'
python -m unittest discover -s tests/browser_e2e -p test_live_privacy.py -k httpbin -v
Remove-Item Env:PLVA_RUN_LIVE_PRIVACY
```

The `-k two_origin_scroll` case passed separately in 21.929s. Navigation-only
checks use `PLVA_RUN_LIVE_BROWSER=1`. Opted-out tests are skips, never acceptance
passes. `diagnose_token_gate.py` is an explicit metadata-only public-site probe.
See `tests/browser_e2e/LIVE-HANDOFF.md` for browser ownership and live receipt checks.
The coordinator's explicit `python -m tests.browser_e2e.run_astra_acceptance`
script reproduces the real-provider case in the integrated workspace, using its
configured local credential without exposing it. Run only during its assigned
browser/CPU window; it makes real provider calls and submits no website forms.

## Verified local real-site results

After extension isolation, the targeted HTTPBin case passed **1/1 in 17.918s**.
There was only one tab. Actual gate metadata: origin and authorized origin
`https://httpbin.org`, focused/visible/editable true, type email, empty autocomplete,
same-origin POST form, search false. The exact synthetic email resolved locally;
the next actual screenshot passed the full-field pixel oracle and decoded
protected-field comparison without clearing/refilling. Unknown email and secret
tokens were rejected without changing the input.

| Actual page/class | Changed pixels masked | Detect/protect time | Protected SHA-256 |
| --- | ---: | ---: | --- |
| HTTPBin email, latest token case | 854; 0 uncovered/retained | 3.775s | `2baa2fcd70b17cad83bb3992c083fbeaba43f6085eadb0710dc1dc2fbccb4bd9` |
| HTTPBin phone, same case | 444; 0 uncovered/retained | 2.519s | `7bcacccf65407974d8364512b732d560c3bdc869860abcc161302df4690889fa` |
| Selenium public web-form textarea email, earlier separate profile | 987; all masked | 16.852s | `4bfcf486e0429cff4e0ae32d07db5219d35b592e5d3a8b8bc3268bd720f07b6d` |

URLs: `https://httpbin.org/forms/post` and
`https://www.selenium.dev/selenium/web/web-form.html`. Earlier Selenium result used
an inner-field difference oracle; current strengthened oracle checks the entire
field with explicit screenshot scaling and stable empty-frame validation. Native
visibility metrics are verifier-only. The matching email protected hash across
fresh values is expected because source values are replaced by the same token.
Observed latency varies with machine contention and is not a performance promise.

## Actual public-navigation provider evidence

The private-data run below is the stronger evidence for the demo; this earlier
public-only run is retained to distinguish Amazon navigation from PII coverage.

Coordinator export: `.plva-evidence/amazon-example-live.json` in its main worktree.
Independent artifact SHA-256 matched
`9ccbd86208a9d97464afe4475c134fd6ef19ffee15c2de21da9337dd11fafa93`.

| Receipt | Protected PNG SHA-256 | Total tokens |
| --- | --- | ---: |
| `resp_07744b585abea20e006aa093064f1c87d08ec4d2d80da4022a` | `e4c257c26208bd3f1aa55f2ecdf8e73005567e45f35085dba86a65db5f9e333c` | 2498 |
| `resp_07744b585abea20e006aa0932d7ce487d0855f4253ea211842` | `80f3e01c743b36690326ec48fbebdb070def8a1fd888fe24ebe10b92bdd92d8c` | 3956 |

Both are web/responded/transmitted HTTP 200, requested and returned model
`gpt-6-astra`, with exactly one outbound PNG matching each audited image. The
initial root and next `previous_response_id` form a complete chain. Function
result `call_pcR5tLy0zcYy9DBffiMYwtNb` matches the preceding `navigate_browser`
call to Example Domain; events record navigation, capture recovery and completion.
Session 5 independently checked consistency; transport observation belongs to the
coordinator. No fake private-value oracle was used. The first NAME mask lacks
raw ground truth and may be a false positive; the second manifest is empty.
This is public navigation evidence, not Amazon PII coverage or scroll/tab proof.

The receipt validator rejects incomplete roots/receipts, broken tool chains,
extra unverified historical images, inconsistent hashes and raw oracle values.
It cannot authenticate transport or prove pixel masking. Its eight regression
tests use explicitly mocked receipts, not live-provider evidence.

## Earlier completed real-Astra private-data run

Coordinator used the production WebRuntime/provider on HTTPBin with a fresh
synthetic email, no mocks. Its oracle verified **845 initial email glyph pixels**
masked, **one exact locally resolved email**, and no raw email or API key in the
outbound audit. Astra typed the token, scrolled 521 pixels, navigated to Example
Domain and finished. Session 5 independently inspected the resulting export:
`.plva-evidence/httpbin-astra-token-live.json`, SHA-256
`a28365ea660f669ccfdf80c6e3cb910c9618d1eb6846ffcc6da41aacb8c635ae`.

**Five web/responded/transmitted HTTP 200 receipts, four distinct protected PNGs**
were consistent: requested/returned model `gpt-6-astra`, usage present, complete
initial-root/response/tool-result linkage, exactly one valid matching PNG in every
outbound request, and execution events for token type, scroll and navigation.

| Receipt | Sent PNG SHA-256 |
| --- | --- |
| `resp_048ab083d6339525006aa0940ac7ac87d0b9cd3c2c9de98152` | `2baa2fcd70b17cad83bb3992c083fbeaba43f6085eadb0710dc1dc2fbccb4bd9` |
| `resp_048ab083d6339525006aa0940fbe3487d0a864254d6694c42b` | `2baa2fcd70b17cad83bb3992c083fbeaba43f6085eadb0710dc1dc2fbccb4bd9` |
| `resp_048ab083d6339525006aa09414cca887d080a5c1bc868fb60d` | `23d24327fb723f748d643d5e1725d39278454d8708902203d79c76ed3b5abe06` |
| `resp_048ab083d6339525006aa0941b68cc87d0a581ed7321b50cbe` | `f5b144db62a1e6049b503237ac1de56dfec324f949f193367d19ffb778a8daff` |
| `resp_048ab083d6339525006aa0942057d487d086f8ee6fb737a428` | `db02e840d6eb7a1880d1491ca34ef524dd10d04b584bc26200c6981630955024` |

Evidence provenance matters: the live script checked initial pixels, exact token
resolution and raw-value absence in memory; Session 5's export-only review checked
receipt/image/history consistency. Full post-token glyph masking was independently
proven in the separate local same-code test, not re-measured for every frame of
this live run. No mock receipt or invented private oracle was used as live proof.

## Completed same-session transitions and Stop

`test_two_origin_scroll_navigation_tab_and_stop` passed **1/1 in 21.929s** using a
native 1200x400 viewport, two real public form origins and one isolated profile.
No document markup, style, route or detector hint was changed.

- HTTPBin tab 1: exact fresh email, **828 changed pixels** fully masked; initial
  hash `8dd12415d4904fb455ebc383cef0a0b818b88b0839e5524fe9dacea306f61e01`.
- Actual 65px scroll moved the field from y=90 to y=25. Its full decoded glyph
  crop matched the original, and all 828 pixels remained masked. Hash
  `563ceffb19a2cad9e933956442d691b2135aab4096e2c8d2d55907d12afe4f66`.
- Selenium tab 2: independent fresh email, **929 pixels** fully masked, hash
  `cc47d46aa7ab0ddd23df59c20f301d89a34b0bacf6d5558494b622499562b6eb`.
- Browser executor navigated tab 2 to Example Domain; captured actual origin and
  tab identity matched. Executor selected HTTPBin tab 1 again; exact email and
  all 828 moved glyph pixels remained masked with the same scrolled hash.
- Stop then rejected attempted typing before input mutation. Manual capture
  remained available and again passed exact/glyph/identity checks. Browser and
  profile cleaned up; no provider or form submissions occurred in this test.

Failure injection additionally exercised actual `command -> run -> observe ->
detector/protect` wiring with mocked transport: forced local detection and
protection failures produced an error state, no protected fallback/cache and zero
provider calls. Together with capture/stop/followup tests, the current boundary
suite passed **5/5 in 0.153s**. This is controlled failure injection, not a live
provider outage experiment.

## History and resolved failures

- Initial fixture-only baseline: 12 tests passed. Later pre-integration run:
  32 tests, 23 passed/9 skipped (3.500s); no sites were visited at that stage.
- Initial detector: 7/10 passed, three exact address/phone values failed due to
  omitted whitespace. Separate diagnostics found zero uncovered source glyphs,
  but token fidelity was wrong. English recognizer `9689c55` fixed these unchanged
  cases: independently **10/10 passed in 13.790s**. No oracle was weakened.
- Initial web runtime sent after Stop during observation. Regression failed,
  coordinator added checks after observation/before send, then **2/2 passed**.
  Current expanded boundary tests **4/4 passed in 0.251s**, covering stop while
  provider response is pending and failed followup capture before second send.
- Earlier live run: Selenium test passed; HTTPBin email pixels passed but token
  gate rejected. A fresh rerun missed exact email OCR (102.004s); no original
  nonce/image retained, so clipping, capture source and transcription causes
  remain unproven. Machine load explains timing, not established OCR cause.
- Actual gate diagnostic later reproduced the cause: extension onboarding tabs
  from Claude, EditThisCookieFork and Loom appeared in a new Edge profile. Selected
  origin became `https://id.atlassian.com`, while only HTTPBin was authorized;
  actual focused handle was not editable. The gate correctly blocked insertion.
  This run masked 822 email pixels first (11.603s), then errored (35.128s total).
  Session 2 disabled extensions; the complete token case then passed as above.
  This cause is not retroactively claimed for the historical OCR miss.

Helper verification: pixel oracle initially 8/8 passed (0.061s); its added strict
moved-field tests bring it to **11/11 passed** (agent run 0.088s). Receipt mock
regressions **8/8 passed** (0.050s). All production dependency copies remain
untracked; Session 5 commits contain only owned test/report files, never secrets.

## Scope and remaining limitations

The scheduled demo acceptance work is complete for the listed cases. No claim is
made that every website/private-data class is reliably detected: the historical
native-input OCR miss remains unresolved, broader fonts/layouts are untested, and
Amazon was tested only as a public navigation page. If another miss occurs,
retain local-only truth/PNG/findings and check complete visibility before assigning
cause. Only the dedicated PLVA browser is protected; unrelated sessions are outside
this boundary. The fresh live run now links strict post-type pixel checks to later
provider receipts; scroll pixel evidence remains a separate independently tested
case, with its exact provenance recorded above.
