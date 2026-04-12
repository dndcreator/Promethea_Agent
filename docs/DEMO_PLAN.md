# Demo Plan

## Goal

Provide an execution-ready plan for a 60–90 second demo, reusable screenshots, and visual assets that strengthen repository presentation without pretending full release maturity.

## 60–90s Video Recommendation

### Style

- Screen-recorded product walkthrough (UI + CLI)
- Minimal narration, clear runtime evidence
- Focus on what already works today

### Timeline Script

#### 0s–12s: Context and Positioning

- Show repository title and one-line summary.
- Show local runtime startup command.

#### 12s–30s: Runtime Health and Surfaces

- Open UI home and show primary controls.
- Run `promethea status base` and `promethea doctor run` in terminal.
- Briefly show API status endpoint response.

#### 30s–55s: Reasoning + Tool + Control Loop

- Send a complex request.
- Show reasoning visibility panel / CLI reasoning watch output.
- Show steer or stop interaction.

#### 55s–75s: Workflow + Audit + Memory Evidence

- Show workflow list/run/checkpoint output.
- Show security audit report excerpt.
- Show memory recall runs or graph panel.

#### 75s–90s: Close and Follow Path

- Show `Current Status: Public Preview / Active Development`.
- End with “Start Here” doc and quickstart link.

## Screenshot Pack (4–6 items)

1. **UI Overview (home + controls)**
   - Meaning: proves there is a concrete usable shell, not only docs.
2. **Reasoning Control Surface (steer/stop visibility)**
   - Meaning: shows controllable runtime reasoning behavior.
3. **CLI Runtime Health (`status` + `doctor`)**
   - Meaning: demonstrates operator-friendly observability.
4. **Workflow State / Checkpoint Output**
   - Meaning: demonstrates resumable multi-step execution.
5. **Security Audit Report Snippet**
   - Meaning: demonstrates traceable runtime actions.
6. **Memory Recall/Graph Evidence**
   - Meaning: demonstrates long-lived assistant memory capability.

## Homepage Hero Architecture Image

### Suggested 3-layer layout

1. **Access Layer**
   - UI / API / CLI / Channels
2. **Runtime Core Layer**
   - Gateway Orchestration, Reasoning, Tool Policy, Workflow, Session/Identity
3. **State + Trust Layer**
   - Memory Backends, Workspace Sandbox, Trace/Audit, Multi-user Isolation

Use simple arrows from top to bottom with one side annotation: “local-first, auditable, resumable”.

## Demo Flow Diagram

Use one left-to-right chain with explicit nodes:

`User Request → Plan → Tool Calls → Workspace Write → Audit Events → Memory Update → Resume`

Arrow labels can include:

- Policy Check (before tool calls)
- User Scope Guard (before memory/workspace)
- Trace Event (at each critical transition)

## Asset Paths and Placeholders

- `docs/assets/hero-architecture.png`
- `docs/assets/demo-flow.png`
- `docs/assets/screenshots/`

Store final screenshots as:

- `docs/assets/screenshots/01-ui-overview.png`
- `docs/assets/screenshots/02-reasoning-control.png`
- `docs/assets/screenshots/03-cli-health.png`
- `docs/assets/screenshots/04-workflow-checkpoint.png`
- `docs/assets/screenshots/05-audit-report.png`
- `docs/assets/screenshots/06-memory-evidence.png`

## Minimal Production Checklist

- Confirm commands in demo are executable in current branch.
- Avoid claiming production readiness or full benchmark completion.
- Keep labels consistent with README and PROJECT_STATUS.
- Ensure visuals map to real repository capabilities only.
