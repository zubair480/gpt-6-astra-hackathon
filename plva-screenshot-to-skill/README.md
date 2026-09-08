# PLVA Screenshot to Skill — hackathon build

A working local loop: **recording → editable skill → rehearsal → fresh inputs for the next run**.

The included support/shipping example uses synthetic evidence. It learns five steps, turns the failed attempt into conditional recovery guidance, and checks each step against the current run's inputs. The HD demo changes the order, product, and protected address for the next workspace. The original two-input contract fixture remains available separately.

## Run the demo

From this repository in PowerShell:

```powershell
.\demo.ps1
```

The script sets up a local Python environment if needed, creates the outputs, and **opens a visual walkthrough in your browser**. It needs Python 3.11+; on this machine it can find Codex's bundled Python. You can pass `-Python C:\path\to\python.exe`. First setup downloads Python dependencies; the **mock demo itself makes no network calls**.

In the walkthrough, follow **Recorded workflow → Learned skill → Skill test lab → Next-run inputs**. Evidence links jump to the recorded screen. The lab shows real Python test results, expected versus actual decisions, and downloadable reports. It also shows the measured learning regression comparison when the tested source matches the current code: **7 failures before, 0 after** across the same 11 cases. The changed workspace is labeled as an unexecuted input.

The default visual demo uses **2400×1440 screens** with large, readable form labels from `fixtures/hd`. These are newly rendered synthetic screens, not upscaled copies. The original 800×480 fixture remains in `fixtures/shipment-demo` for the frozen integration example. Run `python tools/build_hd_fixtures.py` to regenerate the HD fixtures and their trusted synthetic hashes.

The HD screens use a realistic support ticket thread, order details, shipping form, dropdowns, inline validation, and draft status. **Expand screen** opens a larger view of the selected recorded screen; its form controls are part of the synthetic recording, not a second live app.

The viewer uses a graphite studio layout with sidebar navigation, a screenshot filmstrip, an evidence inspector, and compact status counters. Motion follows interactions: the navigation marker slides, screenshots fade during playback, selected test details transition, and buttons respond to hover and press. The interface respects reduced-motion preferences. The progress line represents the recorded screenshot position, not live agent execution.

The launcher always refreshes **`out/visual-demo/demo.html`**, so you can keep the same page bookmarked. If it is already open, refresh the browser tab after a run. Each run's original output package remains in its own dated folder. If your browser does not open, open the printed `demo.html` file yourself. Use `.\demo.ps1 -NoOpen` to generate it without launching a browser. The standalone HTML embeds the synthetic screenshots and needs no server or internet access. It lives outside the four-file portable skill package.

`candidate/SKILL.md` and `review.txt` contain the procedure. `prepared-context.json` contains fresh bindings. `rehearsal.json` records **11 passed cases and 1 pending live-run case**, bound to the exact four-file package. `evaluation.json` tells you what ran. Run B is a prepared handoff, not an executed browser task.

To check any exported candidate again:

```powershell
.\.venv\Scripts\skillforge.exe rehearse out/skill-upgrade-demo/candidate --out out/rehearsal.json
```

For explicit setup on other systems:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate; macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -e .
skillforge demo --out out/demo
```

## Review and use a recording

These commands use the pinned, synthetic example and run from the repository root:

```sh
skillforge import fixtures/shipment-demo
skillforge draft recording-demo-001 --mode mock --out out/candidate
skillforge preview out/candidate
skillforge validate out/candidate
skillforge edit out/candidate --patch examples/review-patch.json --out out/revision-2
skillforge accept out/revision-2 --out out/reviewed
skillforge export out/reviewed --out out/shared
skillforge prepare out/reviewed --bindings fixtures/new-run-bindings.json --capabilities fixtures/capabilities.json
python examples/changed_run.py out/reviewed
```

Use a new output folder each time; existing packages are preserved. CLI output is JSON except `preview`. Exit code 2 means an error, missing input, unsupported capability, or invalid candidate. Candidate preparation is allowed with a visible review warning; preparation never executes actions. `accept` records your review, not a successful rerun.

The committed [sample skill](examples/skills/prepare-a-replacement-shipment-draft-from-a-support-ticket/SKILL.md) is still a **candidate**, with synthetic source checks passed and real reuse pending.

## Integrate with PLVA

The main team supplies `manifest.json`, `events.jsonl`, and sanitized frames following [contracts/v1](contracts/v1). `SkillForge` provides five JSON operations: import, draft, validate, export, and prepare. There is no server, vault, browser runner, or dependency on Qwen/NemoClaw.

- [Integration contract and trust handoff](docs/INTEGRATION.md)
- [Thin Python client](examples/core_client.py)
- [Demo script and integration handoff](docs/HANDOFF.md)
- [Test results and limits](docs/TEST_REPORT.md)
- [What was weak and how the skill was upgraded](docs/SKILL_UPGRADE.md)

## Optional Astra synthesis

Mock mode works without a key. The Astra adapter is implemented and tested with a mocked transport; **no live model call was made for this delivery**. It checks access to exactly `gpt-6-astra` before synthesis and never substitutes another model.

After the core/user approves this exact synthetic bundle for cloud processing:

```powershell
# Set OPENAI_API_KEY in your local shell or secret manager; never commit it.
skillforge approve fixtures/shipment-demo --allow-cloud --trust-role-hints
skillforge import fixtures/shipment-demo
skillforge draft recording-demo-001 --mode astra --out out/astra-candidate
```

`approve` is an explicit local decision, not a sanitizer. For real evidence, the core must approve the complete sanitized bundle first. See [the integration notes](docs/INTEGRATION.md#local-approval).

## Tests

```sh
python -m unittest discover -s tests -v
```

**93 tests pass**, including corrected-action learning, semantic input reuse, conditional recovery, failed outcome handling, legacy package compatibility, actual rehearsal decisions, and correct walkthrough data; see [the current test report](docs/TEST_REPORT.md). Actual Astra synthesis, application control, changed-layout success, and speed improvement remain unmeasured.
