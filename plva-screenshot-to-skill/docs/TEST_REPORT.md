# Hackathon test report

Executed locally on Windows with Python 3.12 on 2026-09-08.

## Automated result

`python -m unittest discover -s tests`: **93 tests passed**, 0 failures, 0 skips; reported test duration **13.624 seconds**, after the skill-quality upgrade. This is unit/integration test duration, not a measured agent-workflow speedup.

| Lane | Tests | Result |
|---|---:|---|
| Evidence import, links, limits, timeline | 17 | Passed |
| Public API, CLI demo, export checks | 10 | Passed |
| Review revisions and prepared context | 14 | Passed |
| Mock synthesis and mocked Astra transport | 15 | Passed |
| Visual walkthrough data, offline assets, report freshness | 6 | Passed |
| Learning behavior regressions | 11 | Passed |
| Skill quality, refinement, legacy compatibility | 10 | Passed |
| Candidate rehearsal scenarios and report integrity | 9 | Passed |
| HD product substitution across workspace inputs | 1 | Passed |

The same 11 learning regressions produced **7 failures on the archived baseline and 0 on the upgrade**. The generated candidate rehearsal reports **11 passed / 0 failed / 1 pending**. See [the measured upgrade](SKILL_UPGRADE.md); pending refers to real application execution, which was not tested.

## Assignment acceptance coverage

| # | Acceptance | Evidence |
|---:|---|---|
| 1 | Screenshots-only inference, no invented click log | Synthesis screenshots-only test; importer order requirement |
| 2 | Ordered action states and frame links | Evidence status/order/reference tests; 18-event fixture |
| 3 | No verified success without outcome evidence | Model-only and empty core-check tests |
| 4 | Failure becomes recovery | Enriched draft test, failed-state precondition removed |
| 5 | Evidence and inference links | Missing-reference tests and schema validation |
| 6 | Private variables and fresh tokens | API round trip and stale-token rejection |
| 7 | Ambiguous roles remain unresolved | Same-class and untrusted-role tests |
| 8 | Untrusted evidence cannot become tested scope-escape instructions | Source/model injection rejection tests; heuristic coverage only |
| 9 | Unknown/raw provenance and text canaries | Exact-bundle cloud gate, canary fields/path/errors tests |
| 10 | Malformed bundles and limits | Unknown version, hash/missing/image/path/size/link/junction tests |
| 11 | Portable skill structure | Four-file export, frontmatter, variables/references, executable rejection |
| 12 | Preparation without execution/plaintext/grants | Runner binding/capability tests; checks reset to unknown |
| 13 | Changed-layout integration | Mock handoff passed; **actual runner execution pending** |
| 14 | New revision invalidates old results | Review edit/review acceptance tests |

## Manual command checks

- Studio redesign: `demo.ps1 -NoOpen -Out out/sleek-studio-demo` refreshed the same bookmarked page with graphite styling, sidebar tabs, screenshot thumbnails, and interaction animations. All six viewer tests passed; JavaScript syntax and static element references were checked. The current learning audit and 11-passed/1-pending rehearsal remain embedded. Browser interaction/visual QA was not performed.
- Skill-quality upgrade: `demo.ps1 -NoOpen -Out out/skill-upgrade-final` rebuilt the bookmarked `out/visual-demo/demo.html`. Verified byte-for-byte equality with the new output; seven embedded 2400×1440 frames from `recording-demo-hd-003`; current learning audit and rehearsal counts; new product/order/address bindings; unique HTML IDs and resolved script element references. Generated JavaScript passed `node --check`, and the exported skill passed Skill Creator's frontmatter check. Browser interaction/visual QA remains unperformed.
- Repeated the 11 learning regressions against the archived baseline with `tools/audit_skill_quality.py`: 4 passed / 7 failed before, 11 passed / 0 failed after. The learning audit is recorded in `src/plva_skill_learning/data/quality-audit.json` and embeds only when source hashes match. Six viewer tests passed after normalizing audit source hashes for Windows line endings.
- `demo.ps1 -Out out/hackathon-demo`: completed; candidate and export validated; fresh binding context ready.
- `python examples/changed_run.py out/hackathon-demo/candidate`: mock hook passed; live adaptation pending.
- `skillforge export out/hackathon-demo/candidate --out examples/skills`: committed four-file candidate package generated.
- `skillforge edit` followed by `accept`: new revision 2 and reviewed copy created successfully; real reuse remained pending.
- Skill Creator `quick_validate.py` on the exported skill: **Skill is valid!** This optional external check used PyYAML 6.0.3 in the local virtual environment; PyYAML is not required to run the product or its tests.
- Git's committed fixture manifest bytes match the working fixture, preserving the pinned trust digest on handoff.
- `demo.ps1 -NoOpen -Out out/visual-demo`: generated the local browser walkthrough successfully, with concise PowerShell output.
- Generated walkthrough JavaScript passes `node --check`. Python tests verify its embedded data matches the actual workflow/prepared context and leaves the skill package unchanged. Browser interaction/visual QA was not performed.
- HD update: all 59 tests passed again in 6.731 seconds. `demo.ps1 -NoOpen -Out out/hd-demo` successfully imported the new pinned 2400×1440 synthetic recording and generated its walkthrough. The completed-form and changed-layout PNGs were visually inspected directly; the original fixture was preserved.
- Realistic UI update: all 59 tests passed in 12.513 seconds. `demo.ps1 -NoOpen -Out out/realistic-demo` completed. The ticket, validation-error, and completed-draft PNGs were visually inspected; the updated viewer JavaScript passes its syntax check. The larger-screen dialog was not exercised through browser automation.
- Stable-page fix: `demo.ps1 -NoOpen -Out out/latest-page-fix` completed and refreshed `out/visual-demo/demo.html`. Verified that this exact bookmarked file matches the new run byte-for-byte and embeds seven 2400×1440 frames from `recording-demo-hd-002`.

The test suite also exercises the public `SkillForge` import/draft/validate/export/prepare sequence without either other workstream.

## Honest limits

Source screenshots and checks are synthetic. Mock success says the package and bindings work; it is not Astra learning or browser execution. Astra transport has mocked tests only. There was no actual live model call, email send, purchase, desktop capture, changed-layout execution, or main-repository modification. The text guard does not prove image redaction, complete private-data detection, or resistance to every prompt injection. Review acceptance and local validation records are not authenticated proof of a real rerun.
