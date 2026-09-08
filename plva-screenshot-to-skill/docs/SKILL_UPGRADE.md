# Skill quality upgrade

The first demo exported a working package, but the procedure was too close to an action transcript. The upgrade improves what gets learned and makes its limits inspectable in the demo.

## Measured weaknesses

The same 11 synthetic recording variations were executed against baseline commit `af354a19178aa37bcd43275477fc63e8e9728a46` and the upgraded code. These tests run the actual import → draft → export → prepare chain with locally approved synthetic evidence.

| Behavior | Before | After |
|---|---|---|
| Ignore an unrelated visible private field | Failed | Passed |
| Ask when a private reference has conflicting classes | Failed | Passed |
| Stop an unsuccessful source workflow from preparing as ready | Failed | Passed |
| Recognize a cancelled source workflow | Failed | Passed |
| Stop at an unrecovered failed final checkpoint | Failed | Passed |
| Remove an explicitly corrected wrong entry from normal steps | Failed | Passed |
| Do not require the old erroneous state before a corrected action | Failed | Passed |
| Ambiguous private/public roles, recovered historical checks, failed-click prerequisites | 4 passed | 4 passed |

Overall: **4 passed / 7 failed before; 11 passed / 0 failed after**. This is bounded behavioral improvement, not a measurement of task execution speed or general agent reliability.

## What the skill now contains

- Goals, source context, semantic field hints, actions, and current-input checkpoints.
- Conditional recovery tied to a recorded error, with the correction and its evidence retained.
- A corrected successful path that omits explicitly superseded wrong writes. Historical failure remains inspectable.
- Required parameters only for relevant inputs; unrelated private metadata remains optional provenance.
- Explicit questions when roles conflict, input values are missing, outcomes are unproven, or checks failed without verified recovery.
- Model refinement checks that preserve input placeholders and missing-evidence questions. Transport tests use mocked model responses.
- Exact legacy v1 Markdown compatibility, so existing four-file exports still validate without rewriting them.

The HD demo now selects a real synthetic product value, **USB-C hub**. Its next-run context supplies **Wireless mouse**, a different order, and a fresh address reference. Selection and outcome checks receive the new product. The screenshot of that changed workspace remains an input, not proof of execution.

## Rehearsal and presentation

`skillforge rehearse <skill> --out <report.json>` calls the real validator and preparation adapter against copied packages and synthetic inputs. It tests fresh/missing inputs, stale or malformed private references, unavailable capabilities, ambiguous roles, broken evidence, and failed/unknown outcomes. Eleven cases pass for the demo; actual changed-layout execution is the twelfth case and stays pending.

The **Skill test lab** shows each case's change, expected decision, actual decision, and adapter explanation. Tests run during demo generation; page interactions inspect recorded results. Reports remain outside the portable package. A package digest prevents a stale candidate report from appearing current. The learning comparison is shown only when its recorded source hashes match the current implementation, with line endings normalized for Windows checkouts.

To reproduce the learning comparison, first extract the baseline commit into an isolated folder, then run:

```powershell
.\.venv\Scripts\python.exe tools/audit_skill_quality.py --baseline out/skill-audit/baseline --baseline-commit af354a19178aa37bcd43275477fc63e8e9728a46
.\demo.ps1 -NoOpen
```

Without `--baseline`, the audit measures the current suite only. The emitted JSON includes case results, source hashes, the suite hash, and timestamp. The full automated suite contains **93 passing tests**.

## Remaining limitation

This is still a synthetic offline learning module. A recorded correction establishes a narrow reusable procedure; it does not establish general skill discovery. The implementation recognizes explicitly linked corrections, not arbitrary causal relationships between screenshots. Astra synthesis and visual adaptation require a real approved recording, live model access, and the existing main PLVA runtime. No second runtime or infrastructure was added.
