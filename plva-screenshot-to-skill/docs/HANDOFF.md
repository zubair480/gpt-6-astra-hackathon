# Hackathon handoff

Run `demo.ps1` from the repository root. It opens a local visual walkthrough with recorded-screen playback, the generated skill, and fresh next-run inputs. It also writes the inspectable skill and prepared context. Use `-NoOpen` to generate without opening your browser.

First contract commit: `dbdd0ea`. The original CLI handoff remains pinned at `hackathon-handoff-v1`. The visual walkthrough update is pinned by **`hackathon-visual-demo-v1`**; use `git rev-parse hackathon-visual-demo-v1` to resolve its exact commit. No remote has been created or pushed.

## Two-minute demonstration

1. Show `fixtures/hd/shipment-demo`: synthetic support ticket, replacement form, failed early attempt, correction, completed draft, and checks.
2. Run `demo.ps1`. In the browser, click **Play recording**, then **Review learned skill**. Point out five semantic steps, recovery guidance, and `{{customer_shipping_address}}`. Evidence links jump back to the source screen; Download SKILL.md gives the actual generated file.
3. Open **Skill test lab**. Show the 7 → 0 learning failures comparison, then inspect fresh inputs, an unproven outcome, and the pending changed-layout case. Expected refusals count as test passes.
4. Open **Next-run inputs**: field positions, product, order, token, and button label differ. Show that selection and outcome checks contain the new product, with check results reset to unknown. This is an input prepared for Run B.
5. State the boundary precisely: the independent learning/handoff loop works; the team's existing Astra runner still needs to perform the changed-layout execution.

To record actual human review, run `skillforge preview`, `edit`, and `accept` as shown in [README](../README.md). The one-command demo does not pretend you accepted a candidate. Its output is labeled mock/synthetic.

## Team integration checklist

- Recorder teammate: implement the frozen [manifest](../contracts/v1/manifest.schema.json) and [event](../contracts/v1/event.schema.json) contract, starting from [the complete fixture](../fixtures/shipment-demo/manifest.json).
- Runtime teammate: call `prepare_run` with fresh core-issued tokens and your actual capabilities; supply its result to the existing agent along with current observations. Use [core_client.py](../examples/core_client.py) and [changed_run.py](../examples/changed_run.py).
- Shared procedure: [generated SKILL.md](../examples/skills/prepare-a-replacement-shipment-draft-from-a-support-ticket/SKILL.md), with machine-readable workflow, evidence map, and separate validation file beside it.
- Verification: [93-test report](TEST_REPORT.md), [quality upgrade](SKILL_UPGRADE.md), and exact [integration behavior](INTEGRATION.md).

## What works now

Approved local import, bounded timeline/windows, deterministic evidence-based drafting, guarded Astra adapter with mocked tests, semantic inputs, evidence-linked export, CLI preview/edit/accept, revision invalidation, and typed second-run preparation. Only Python libraries and files are required.

## Remaining dependencies

Live synthesis needs confirmed `gpt-6-astra` account access, local credentials, and explicit cloud approval for the exact evidence bundle. Actual reuse needs the main team's existing runner, current approved screenshots, fresh token issuance, and new outcome checks. No substitute browser runner was built. Image privacy assurance remains the already-existing privacy workstream's responsibility.

The main team has not yet supplied its recorder/runtime. No external teammate destination was specified, so this handoff is local and ready to share. No infrastructure or additional account setup was added to run the mock demo.
