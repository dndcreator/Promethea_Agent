# Promethea — A Memory-Native Agent Runtime for Long-Lived AI Systems

Promethea is a local-first agent runtime for long-lived AI systems that need memory, recovery, auditability, and multi-user isolation. It treats memory, workflow, policy, audit, and user boundaries as runtime primitives, not post-hoc plugins.

## What Promethea Is

Promethea is a runtime layer for building and operating AI assistants that must run beyond single-turn demos.

It is designed for systems where you need to:

- keep user-scoped memory over time
- run tool and workflow actions with explicit policy checks
- produce audit traces for important runtime events
- recover and resume multi-step execution
- support multiple interfaces (UI, API, CLI, channels) on one core runtime

It is **not** just a prompt template repo and **not** only a chat wrapper.

## What Works Today

Already explorable in the current repository:

- local-first runtime with Web UI, HTTP API, and CLI surfaces
- pluggable memory backends (`flat_memory`, `sqlite_graph`, `neo4j`) with recall/write flows
- resumable workflow engine with checkpoints and approval-style steps
- structured runtime audit and trace events for security/operations visibility
- explicit multi-user isolation model across sessions, memory, config, and workspace boundaries
- tool/policy/sandbox-aware execution paths through gateway services
- ToT/ReAct reasoning runtime hooks with steer/stop control surfaces

## Why It Is Different

1. Most agent projects stop at first-round tool calling; Promethea focuses on what happens after that: memory lifecycle, workflow continuity, policy, and audit.
2. Many systems treat memory/audit/policy as optional integrations; Promethea puts them inside the runtime contract.
3. Promethea is local-first and multi-surface by design, not tied to a single hosted GUI.

## Quick Demo

Recommended showcase chain for first-time visitors:

`User Request → Plan → Tool Calls → Workspace Write → Audit Events → Memory Update → Resume`

![Promethea Demo Flow](docs/assets/demo-flow.png)

If you want to script this quickly, use:

```bash
promethea status base
promethea doctor run
promethea reasoning list
promethea workflow list
promethea security report --limit 20
```

## 3-Minute Quickstart

```bash
git clone https://github.com/dndcreator/Promethea_Agent.git
cd Promethea_Agent
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# copy env template then fill API__API_KEY / API__BASE_URL / API__MODEL
# Windows: copy env.example .env
# macOS/Linux: cp env.example .env

python start_gateway_service.py
```

Open:

- UI: `http://127.0.0.1:8000/UI/index.html`
- API: `http://127.0.0.1:8000/api/status`

Detailed setup:

- [QUICK_START.md](QUICK_START.md)
- [docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)
- [docs/getting-started/real-user-setup.md](docs/getting-started/real-user-setup.md)

## Current Status

**Stage: Public Preview / Active Development**

What this means today:

- Runtime core, memory/workflow/audit/policy foundations, CLI/API/UI surfaces are already usable and worth exploring.
- Benchmark expansion, packaging polish, docs polish, and release-process hardening are still in progress.
- This is a serious build with real capabilities, but not presented as a finalized commercial product release.

## Where to Read Next

Start from the path that matches your goal:

- Start here navigator: [docs/GET_STARTED_HERE.md](docs/GET_STARTED_HERE.md)
- Product overview: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)
- Runtime design: [docs/runtime-overview.md](docs/runtime-overview.md)
- Docs hub: [docs/README.md](docs/README.md)
- Roadmap: [ROADMAP.md](ROADMAP.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Contribution path: [CONTRIBUTING.md](CONTRIBUTING.md)

---

## Architecture Contract Endpoints

Machine-readable contract/profile endpoints:

- `/api/ops/capabilities`
- `/api/ops/abstractions`
- `/api/ops/protocol`
- `/api/ops/methods`
- `/api/ops/http-contracts`
- `/api/ops/framework-check`
- `/api/ops/surfaces`
- `/api/ops/readiness`
- `/api/ops/runbook`

Reference:

- [docs/infrastructure-profile.md](docs/infrastructure-profile.md)

## Core Capability Areas

### Memory Runtime

- Layered memory model and recall/write pipeline
- Backend options for different deployment constraints
- Write/recall policy controls and inspection points

References:

- [docs/architecture/memory-model.md](docs/architecture/memory-model.md)
- [memory/README.md](memory/README.md)

### Workflow Runtime

- Multi-step workflow definitions
- Checkpoint/resume and approval-style flow control
- Artifact writes through workspace boundaries

References:

- [docs/architecture/workflow-model.md](docs/architecture/workflow-model.md)
- [gateway/README.md](gateway/README.md)

### Policy, Sandbox, and Audit

- Runtime policy-aware tool execution
- Workspace/sandbox boundary controls
- Trace/audit events for operations and security analysis

References:

- [docs/architecture/security-model.md](docs/architecture/security-model.md)
- [SECURITY.md](SECURITY.md)

### Interfaces and Access Surfaces

- Web UI (`UI/`)
- HTTP API (`gateway/http`)
- CLI (`promethea_cli/`)
- channel adapters (`channels/`)

References:

- [docs/api-reference.md](docs/api-reference.md)
- [docs/cli-reference.md](docs/cli-reference.md)
- [UI/README.md](UI/README.md)

## Benchmark and Validation (Current)

Current repository validation assets include:

- benchmark tasks: [benchmarks/general_capability_tasks.json](benchmarks/general_capability_tasks.json)
- benchmark harness: [scripts/run_general_benchmark.py](scripts/run_general_benchmark.py)
- benchmark-related tests: [tests/test_general_benchmark_harness.py](tests/test_general_benchmark_harness.py)
- release/business playbooks: [docs/full-business-test-playbook.md](docs/full-business-test-playbook.md)

This is a useful baseline for public preview, while broader public benchmark coverage is still being expanded.

## Documentation Map

- Docs hub: [docs/README.md](docs/README.md)
- Showcase: [docs/SHOWCASE.md](docs/SHOWCASE.md)
- Project status: [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)
- Demo scenarios: [docs/DEMO_SCENARIOS.md](docs/DEMO_SCENARIOS.md)
- Why Promethea: [docs/WHY_PROMETHEA.md](docs/WHY_PROMETHEA.md)
- Demo production plan: [docs/DEMO_PLAN.md](docs/DEMO_PLAN.md)

## Community and Governance

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [MAINTAINERS.md](MAINTAINERS.md)

## License

MIT — see [LICENSE](LICENSE).

[![GitHub Stars](https://img.shields.io/github/stars/dndcreator/Promethea_Agent?style=social)](https://github.com/dndcreator/Promethea_Agent)
