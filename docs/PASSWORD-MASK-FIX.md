# Password mask placement correction

Verified September 8, 2026 (America/Los_Angeles).

The reported `[SECRET_2]` mask covered the nearby **Forgot password?** link instead
of the password glyphs. Two causes combined: label pairing preferred neighboring
text to the field below, and OCR omitted the small native password dots.

## Correction

- Ignore narrow recovery/help phrases when inferring password values, and prefer
  visible masked-glyph runs. Explicitly labelled secrets remain protected, even
  when their text resembles a helper phrase.
- Find compact, repeated password glyphs locally in the screenshot near a
  recognized Password/Passcode label when OCR omits them. Bounds come from the
  visible pixels, with padding; no DOM coordinates or expected values enter the
  detector.
- Ignore stale helper phrases inferred as secrets, while preserving legitimate
  local discoveries. Recognized prose, borders, outlines, and carets do not
  become fallback glyph runs in the tested cases.

Secret-token resolution and destination restrictions are unchanged. Provider,
browser navigation, history, and UI behavior were not changed by this correction.

## Evidence

The unchanged baseline failed all six initial generated field configurations.
The corrected implementation passed all 51 tests in the command below, with no
skips, including real OCR and the existing five-category pixel checks, secret
blocking, observation caching, provider boundaries, and stop/failure behavior.

```powershell
$env:PLVA_TEST_OCR='1'
python -m unittest tests.test_secret_pairing tests.test_password_components tests.test_password_masking tests.test_privacy tests.test_detection tests.browser_e2e.test_pixel_privacy tests.test_web_observation tests.browser_e2e.test_web_runtime_boundary -v
```

The independent missing-glyph checks cover light/dark fields, position changes,
1.5× scaling, empty fields, missing labels, and border/caret negatives. The glyph
oracle compares a generated empty field to the same field with glyphs; it does
not derive truth from the detector's rectangles.

The reported frame was also processed locally in memory with the final integrated
detector. An independent grayscale/component check found **133 password glyph
pixels: zero uncovered, zero retained**, with the recovery-link region unchanged.
An earlier grayscale conversion counted 125; both checks found full coverage.
The corrected rectangle was `(461, 196, 65, 10)` in screenshot pixels. No raw frame,
recognized private text, password, or vault value was written by this check or
sent to a provider. There were no live Astra calls in this bug-fix verification.

After restart, the operator UI successfully opened `https://example.com/` in the
managed browser and produced a new protected preview. Manual **Refresh preview**
also succeeded; detector status was ready, with no error, zero model calls, and
zero audit requests. This checks the running capture/protection path; the page
contains no password, so password coverage is established by the checks above.

## Apply and retest

Restart PLVA once after updating: the detector and observation cache live in
memory. The running local app was restarted with the correction. Reopen your
website, enter a test password manually, then choose **Refresh preview**. Confirm
that the secret mask covers the password glyphs and leaves the recovery link
visible. Token numbers can change when a new privacy session begins.

The pre-restart history was retained in a local evidence backup. Those historical
images retain their original masking, including the old defect; they were not
rewritten or restored into the new session. API keys entered only through the UI
must be entered again after a restart; a configured environment key is loaded
normally.

## Limits

This is a scoped correction, not universal password detection. The fallback
requires a recognized English Password/Passcode label, sufficiently contrasting
2–14px glyph components, and a nearby regular run of 3–32 glyphs. Unusual fonts,
low contrast, missing labels, or distant fields can still be missed. Decorative
dots visually identical to password dots can remain ambiguous.
