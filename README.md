# Promethea

**A memory-native, reasoning-aware, multi-user-safe Agent Runtime.**

> Not a chatbot wrapper. Not a prompt chain.  
> A complete runtime for long-lived, multi-turn, multi-task AI agents —  
> that can remember you, plan actions, execute tools safely, and deliver artifacts you can actually trust.

---

## Why Promethea?

Most agent frameworks solve the "make an LLM call a tool" problem.  
Promethea solves what comes after:

| Problem | What Promethea does |
|---|---|
| Agent forgets who you are after 10 messages | Layered long-term memory: hot / warm / cold, graph-backed, per-user owned |
| Tool calls are fire-and-forget black boxes | ToolSpec + ToolPolicy + full audit trace on every invocation |
| Multi-user = data leaks between users | Four namespace layers, enforced at runtime, auditable |
| Long tasks die mid-way | Resumable workflow engine with checkpoints and human-approval gates |
| "What did the agent do?" is unanswerable | Structured trace + audit events on every memory write, tool call, and workspace write |
| Config drifts, prod breaks silently | Versioned config schema with migration path and deprecation warnings |

---

## Feature Highlights

### 🧠 Multi-Layer Memory System
Three pluggable backends — no database required for basic use:

- **`flat_memory`** — JSONL file, zero dependencies, works out of the box
- **`sqlite_graph`** — SQLite with graph recall via recursive CTE; semantic + structural search
- **`neo4j`** — Full hot/warm/cold/forgetting stack; production-grade multi-session memory

Memory is **governed, not just stored**:
- `MemoryWriteGate` decides allow / deny / defer before any long-term write
- `MemoryRecallPolicy` controls fast / deep / workflow recall modes
- MEF (Memory Exchange Format) enables lossless migration between backends

### ⚙️ Workflow Engine
Linear, resumable, human-in-the-loop workflows:

- Step types: `reasoning_step`, `tool_step`, `artifact_step`, `approval_step`, `memory_step`, `summary_step`
- Checkpoint capture at every step boundary
- Pause / resume / retry / human approval gate
- Artifacts written directly into workspace sandbox

### 🔒 Security-First Runtime
Four enforced namespace layers:

- **Config namespace** — user-scoped policies, no cross-user bleed
- **Session namespace** — session ownership bound to user identity
- **Memory namespace** — recall and write scoped to owning user
- **Workspace namespace** — sandboxed file access, path-escape protection

Security audit is queryable in real time: `GET /api/security/audit/report`

### 🛠️ Tool & Skill System
- Unified `ToolRegistry` covers local tools, MCP services, and agent tools
- `ToolSpec` carries capability type, side-effect level, permission scope, timeout hints
- `ToolPolicy` enforces allow/deny at runtime, not just at prompt time
- `Skills` bundle tool allowlists + system instructions + evaluation cases into deployable capability packs

### 📡 Multi-Channel, One Runtime
Channel adapters normalize every input source to the same gateway contract:
- Web UI (built-in)
- HTTP API
- Telegram
- Tauri desktop shell (Windows / macOS / Linux)
- Extensible to any channel without touching the core pipeline

### 🔍 Observability Built In
- Structured `TraceEvent` + `AuditEvent` on every significant operation
- `SecurityAuditService` generates per-user audit reports
- MCP service health snapshots (`online / offline / degraded`)
- `MemoryRecallInspector` — see exactly what was recalled, dropped, and why

---

## Quickstart

### Requirements

- Python ≥ 3.10
- pip / venv

### 1. Install

```bash
git clone https://github.com/<your-org>/Promethea_Agent.git
cd Promethea_Agent

python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt
```

### 2. Configure

```bash
# Windows
copy example.env .env

# macOS / Linux
cp example.env .env
```

Open `.env` and set **at minimum these three fields** (they are coupled — all three must match your provider):

```bash
# Option A: OpenRouter (recommended for first-time users)
API__API_KEY=sk-or-your-key-here
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=openai/gpt-4.1-mini

# Option B: OpenAI directly
API__API_KEY=sk-your-openai-key
API__BASE_URL=https://api.openai.com/v1
API__MODEL=gpt-4.1-mini

# Option C: Local model (any OpenAI-compatible server)
API__API_KEY=dummy-local-key
API__BASE_URL=http://127.0.0.1:8001/v1
API__MODEL=your-local-model-id
```

> ⚠️ `API__BASE_URL` and `API__MODEL` must match. Changing only the key will not work.

Choose a memory backend (start here if you want zero external dependencies):

```bash
MEMORY__ENABLED=true
MEMORY__STORE_BACKEND=sqlite_graph   # or flat_memory
```

### 3. Run

```bash
python start_gateway_service.py
```

Visit `http://127.0.0.1:8000/UI/index.html` — it opens automatically.

---

## Architecture in 90 Seconds

```
┌─────────────────────────────────────────────────────────────┐
│                     Interface Layer                         │
│          Web UI  │  HTTP API  │  Telegram  │  Tauri         │
└────────────────────────┬────────────────────────────────────┘
                         │ GatewayRequest
┌────────────────────────▼────────────────────────────────────┐
│                  Gateway Control Plane                      │
│   Session ▸ RunContext ▸ Pipeline ▸ Audit ▸ EventBus        │
└──┬──────────┬──────────┬──────────┬───────────┬────────────┘
   │          │          │          │           │
Memory    Tools/MCP   Skills    Workspace   Workflow
Layer     Layer       Layer     Sandbox     Engine
   │          │          │          │           │
   └──────────┴──────────┴──────────┴───────────┘
                         │
         ┌───────────────▼──────────────┐
         │   Security / Observability   │
         │  Namespace  Trace  Audit     │
         └──────────────────────────────┘
```

Six-stage pipeline per request:

1. **Input Normalization** — user identity, trace_id, channel normalization
2. **Mode Detection** — fast / deep / workflow
3. **Memory Recall** — layered, policy-controlled, reason-tagged
4. **Planning / Reasoning** — ReAct-Tree-of-Thought, resumable nodes
5. **Tool Execution** — policy-checked, fully traced
6. **Response Synthesis** — artifact write, memory write gate, audit flush

Full design: [`docs/architecture/runtime-overview.md`](docs/architecture/runtime-overview.md)

---

## Configuration Reference

See [`docs/configuration.md`](docs/configuration.md) for the complete reference.

Key sections:

| Section | Key fields | Notes |
|---|---|---|
| `api` | `api_key`, `base_url`, `model` | All three must match your provider |
| `memory` | `enabled`, `store_backend` | Start with `sqlite_graph` |
| `memory.neo4j` | `uri`, `username`, `password` | Only needed for Neo4j backend |
| `sandbox` | `enabled`, `profile` | Set `profile=strict` in production |
| `reasoning` | `enabled`, `mode` | `react_tot` is the only supported mode |

---

## Docs

| Document | What it covers |
|---|---|
| [`docs/architecture/runtime-overview.md`](docs/architecture/runtime-overview.md) | Full runtime design, pipeline stages, core objects |
| [`docs/architecture/memory-model.md`](docs/architecture/memory-model.md) | Memory layers, write gate, recall policy |
| [`docs/architecture/security-model.md`](docs/architecture/security-model.md) | Namespace layers, enforcement points, audit |
| [`docs/architecture/workflow-model.md`](docs/architecture/workflow-model.md) | Workflow engine, step types, checkpoint policy |
| [`docs/architecture/tool-runtime.md`](docs/architecture/tool-runtime.md) | ToolSpec, ToolRegistry, ToolPolicy |
| [`docs/configuration.md`](docs/configuration.md) | Full configuration reference |
| [`docs/quickstart-local-model.md`](docs/quickstart-local-model.md) | Using local models (vLLM, Ollama, etc.) |
| [`docs/scenario-workflow-audit.md`](docs/scenario-workflow-audit.md) | End-to-end demo: workflow + workspace + audit |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute |

---

## Scenarios

### Run a workflow that saves an artifact

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/plan_and_save \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "Design a memory system architecture",
    "session_id": "s1",
    "workspace_id": "myproject",
    "user_id": "u1"
  }'
```

The agent will:
1. Run a `reasoning_step` to generate the plan
2. Write the artifact via `artifact_step` to `workspace/u1/myproject/outputs/plan.md`
3. Emit a `workspace.artifact.written` audit event

### Inspect the security audit log

```bash
curl "http://127.0.0.1:8000/api/security/audit/report?user_id=u1"
```

Returns a structured report with: namespace violations, workspace blocked events, side-effect tool calls, secret access attempts.

### Switch memory backend without data loss

```python
from memory.adapter import MemoryAdapter

adapter = MemoryAdapter()
result = adapter.migrate_backend("flat_memory", mode="cutover")
# {"ok": True, "mode": "cutover", "active_backend": "flat_memory", ...}
```

---

## Comparison

| | Promethea | OpenClaw |
|---|---|---|
| Multi-layer memory (hot/warm/cold) | ✅ | ⚠️ varies |
| Memory write governance (allow/deny/defer) | ✅ | ❌ |
| Memory backend migration (MEF) | ✅ | ❌ |
| Namespace isolation (4 layers) | ✅ | ⚠️ partial |
| Resumable workflow + human approval | ✅ | ⚠️ varies |
| Workspace sandbox + path escape protection | ✅ | ⚠️ varies |
| Real-time security audit report | ✅ | ❌ |
| ToolSpec + ToolPolicy at runtime | ✅ | ⚠️ varies |
| MCP health panel | ✅ | ⚠️ varies |
| Local model support (OpenAI-compatible) | ✅ | ✅ |
| Channel adapter framework | ✅ | ✅ |
| Tauri desktop shell | ✅ | ❌ |

---

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md).

Quick start for contributors:

```bash
pip install -r requirements.txt
pytest tests/test_reasoning_service.py tests/test_memory_regressions.py \
       tests/test_tool_service.py tests/test_workspace_sandbox.py
```

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Share

If Promethea helps you build something real, tell someone.

> A memory-native agent runtime for long-lived tasks — with governance, workspace, workflow, and multi-user safety built in.  
> Zero cloud lock-in. Runs on your machine. Open source.

[![GitHub Stars](https://img.shields.io/github/stars/your-org/Promethea_Agent?style=social)](https://github.com/your-org/Promethea_Agent)
