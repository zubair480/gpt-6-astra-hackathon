# Workstream status

| Track | Owner | Status | Evidence | Blocker | Next handoff |
|---|---|---|---|---|---|
| v1 contracts, fixture, CLI, integration | Lead | Complete for standalone demo | dbdd0ea; 9 integration tests; demo.ps1 | Main team integration pending | docs/HANDOFF.md; hackathon-handoff-v1 |
| Evidence ingestion and timeline | Evidence agent | Complete | 17 passing tests; exact fixture and reference validation | None for local demo | v1 producer contract to recorder teammate |
| Synthesis and export | Synthesis agent | Complete for mock; live pending | 15 passing tests; generated four-file skill | Actual Astra call not exercised | Core-approved cloud bundle and model access |
| Review and runner preparation | Review agent | Complete for handoff; execution pending | 14 passing tests; changed-run mock hook passed | Main runtime unavailable | Supply prepared context to existing runner |
| Visual demo and browser opening | Lead; review agent tests | Complete | Self-contained demo.html; 4 additional tests; concise demo.ps1 launcher | Actual Astra execution remains separate | hackathon-visual-demo-v1 |
| HD demo screens | Lead | Complete | 2400×1440 fixture; readable form labels; HD demo passed; original recording preserved | None for local viewing | Default demo uses fixtures/hd |
| Realistic support/shipping UI | Lead | Complete | Ticket thread, order panel, form validation, draft status; expanded image view; all 59 tests pass | None for local demo generation | Run demo.ps1 for the updated version |

Latest upgrade: **93 tests pass**. Eleven learning regression cases improved from **7 failures to 0**. The demo includes conditional recovery, corrected-action learning, product substitution, legacy package compatibility, and a test lab with **11 actual offline cases passed / 1 live case pending**. Details are in `docs/SKILL_UPGRADE.md`.

Actual changed-layout execution is pending integration with the main PLVA runtime. Synthetic screens are input fixtures, not recordings of a live agent.
