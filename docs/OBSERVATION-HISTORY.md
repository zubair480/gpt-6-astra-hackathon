# Protected observation history

The top history strip retains previous protected browser observations. Selecting
a thumbnail opens a separate historical panel; the latest preview continues to
update independently. Historical images are local observations. Only a matching
recorded provider receipt establishes that a particular observation was sent.

## Retention and identity

- History belongs to the dedicated browser session. Starting another web task
  preserves earlier previews. Close or a switch to/from the prepared fixture
  clears the history and changes its epoch.
- A sequence number identifies chronology independently of the run's step count.
  Different agent observations remain distinct even if their PNGs are identical.
  Repeated unchanged idle polling consolidates the latest observation. Returning
  from image A to B to A creates a new step; explicit navigation/tab selection
  can also retain a new step with identical pixels.
- At most 128 observations and 64 MiB of unique protected PNG bytes are kept in
  memory. Identical images share storage. Oldest entries are evicted first;
  the viewer reports the count. The latest preview remains independent of history.
- No raw screenshots, vault values, page titles or URLs are retained in this
  history. It stores the already protected PNG returned by the privacy layer.
  Detector coverage limits still apply to those protected images.

## Local API

`GET /api/state` includes `observation_history` (oldest first), `history_epoch`,
`history_limit`, and `history_dropped`. `GET /api/history` returns those same fields.

Each entry contains `id`, `sequence`, `step`, `source`, `frame_hash`, `tab_id`,
`created_at`, `reason`, `image_url`, and `status`. Optional `request_id`,
`response_id`, and `transmitted` fields come from the actual request audit.
The corresponding audit contains `observation_id`; matching uses this identity,
never the image hash alone.

`GET /api/history/{id}/image` returns only the protected PNG with
`Cache-Control: no-store`. Removed or cleared IDs return 404. Image bytes are not
repeated in the one-second state poll. The current raw/operator preview remains
separate and is never read by the history UI.

## Verification

26 targeted tests passed for history storage/API, runtime observation integration,
the original action boundary, and stop/failure handling. They cover duplicate
polls, repeated task images, A→B→A, exact receipt links, byte/count eviction,
unavailable old IDs, preservation across Start, and clearing on Close/source reset.
Failures append no history entry and clear the current observation identity while
leaving earlier successful history available. Provider receipt tests use mocks;
this feature does not require a new model call.

Actual dashboard verification also passed using example.com and IANA. Two
protected images loaded through the local endpoints; selecting the first stayed
fixed while the latest view changed. Repeated captures increased the live step
counter without duplicating the two history entries. Return and Close behaved as
expected, with zero model calls. The single-viewport layout had one history strip
above the latest views with no overlap.

```powershell
python -m unittest tests.test_history tests.test_web_observation tests.browser_e2e.test_web_runtime_boundary tests.test_runtime -q
```
