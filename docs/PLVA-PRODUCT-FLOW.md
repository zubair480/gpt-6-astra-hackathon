# PLVA: private work becomes a reusable skill

Combined integration flow before branch merge. The private reasoning lane assumes completion of the intended NemoClaw/OpenShell deployment; current handoff still marks it untested. No OpenCL/OpenClaw integration was found.

```mermaid
flowchart TD
userTask(["User asks: complete this browser task"])
subgraph runFlow ["1. DO THE TASK WITH PRIVACY"]
openPage["Open website in PLVA browser"]
protectPage["PLVA hides detected private details"]
localVault[("Real values stay in local vault")]
astraPlan["Astra sees protected page and proposes action"]
localGate{"PLVA permits the action?"}
stopAction["Block or request user approval"]
executeAction["Resolve allowed tokens locally and act"]
checkResult{"Task outcome verified?"}
endRun["Task complete"]
end
subgraph reasonFlow ["2. OPTIONAL PRIVATE REASONING"]
privateNeed["Need to compare hidden values or review behavior"]
localReason["Local Qwen inside intended NemoClaw / OpenShell boundary"]
privateAnswer["Return tokens or bounded recommendation"]
end
subgraph skillFlow ["3. TURN THE WORK INTO A REUSABLE SKILL"]
safeEvidence["Export sanitized screenshots, actions and checks"]
draftSkill["Skill Studio drafts steps and recovery guidance"]
humanReview["User reviews and edits the candidate"]
saveSkill["Save SKILL.md and structured workflow"]
freshInputs["Next task: load skill with fresh inputs and tokens"]
end
userTask --> openPage
openPage --> protectPage
protectPage -->|"Values stored locally"| localVault
protectPage -->|"Protected image and references"| astraPlan
astraPlan --> localGate
astraPlan -.->|"When private computation is needed"| privateNeed
localGate -.->|"When local advice is needed"| privateNeed
privateNeed --> localReason
localReason --> privateAnswer
privateAnswer -->|"Core still decides"| localGate
localGate -->|"No"| stopAction
localGate -->|"Yes"| executeAction
localVault -->|"Only for permitted execution"| executeAction
executeAction --> checkResult
checkResult -->|"More work: protect the next observation"| protectPage
checkResult -->|"Yes"| endRun
endRun -.->|"Create a skill"| safeEvidence
safeEvidence --> draftSkill
draftSkill --> humanReview
humanReview --> saveSkill
saveSkill --> freshInputs
freshInputs -.->|"Run through the same privacy checks"| openPage
classDef cloud fill:#dbeafe,stroke:#2563eb,color:#102347
classDef local fill:#d1fae5,stroke:#059669,color:#062d24
classDef skill fill:#ede9fe,stroke:#7c3aed,color:#2e1065
class astraPlan cloud
class protectPage,localVault,localGate,executeAction,localReason,privateAnswer local
class safeEvidence,draftSkill,humanReview,saveSkill,freshInputs skill
```

## Fetched branch evidence

- `codex/plva-demo` at `c214501`: managed Windows Edge, screenshot protection, local token handling and Astra computer tool integration.
- `feat/private-reasoning-module` at `f7804c8`: approval, computation and trace-review service. Handoff reports real Qwen/Astra runs and macOS sandbox-exec tests. NemoClaw/OpenShell remains untested.
- `codex/screenshot-to-skill-studio` at `315cc62`: evidence import, drafting, review/edit/accept, export and next-run preparation. Handoff reports 93 tests. Live Astra synthesis and changed-layout execution remain unmeasured.

Skill drafting currently has a local deterministic path and an optional Astra adapter tested with mocked transport. Review approval does not prove execution success. Reuse requires fresh tokens, current policy and new outcome checks.

No branches were merged. The diagram illustrates how the workstreams connect after integration; it is not a claim of a verified combined run. Test results above are branch-reported, not rerun for this diagram.

