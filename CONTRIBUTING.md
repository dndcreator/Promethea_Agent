# Contributing to Promethea

Thank you for your interest. This document explains how to set up a development environment, run the test suite, and submit changes.

---

## Table of Contents

- [Development environment](#development-environment)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [Project structure](#project-structure)
- [Submitting a pull request](#submitting-a-pull-request)
- [Architecture decision records (ADRs)](#architecture-decision-records)
- [Backlog tasks](#backlog-tasks)
- [Definition of done](#definition-of-done)
- [Things not to do](#things-not-to-do)

---

## Development environment

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

# Create a local config (minimum: set API__API_KEY, API__BASE_URL, API__MODEL)
cp example.env .env
```

---

## Running tests

### Minimum regression set (run before every PR)

```bash
pytest tests/test_reasoning_service.py \
       tests/test_memory_regressions.py \
       tests/test_tool_service.py \
       tests/test_workspace_sandbox.py \
       tests/test_workflow_engine_mvp.py
```

### Full suite (no live services required)

```bash
python tests/run_all_tests.py
```

### Full suite with coverage

```bash
python tests/run_all_tests.py --coverage
```

### Enable live integration tests (requires running services)

```bash
PROMETHEA_LIVE_TEST=1 python tests/run_all_tests.py --live
```

### Single file

```bash
python tests/run_all_tests.py --file test_memory_regressions.py
```

---

## Code style

We use `black`, `isort`, and `flake8`. Run before committing:

```bash
black .
isort .
flake8 .
```

Configuration lives in `pyproject.toml`.

---

## Project structure

```
gateway/          Core control plane, pipeline, tools, workflow, workspace, security
memory/           Memory backends (sqlite_graph, flat_memory, neo4j) and adapter
agentkit/         MCP manager, tool implementations, sandboxing
channels/         Channel adapters (web, HTTP, Telegram, ...)
computer/         Computer-control primitives (screen, browser, filesystem, process)
skills/           Skill schema, registry, and official packs
docs/             Architecture docs, ADRs, backlogs, playbooks
tests/            Full test suite
config/           default.json — shipped defaults (no secrets here)
example.env       Template for user configuration
```

Key entry point: `gateway/app.py` — FastAPI application.  
Startup script: `start_gateway_service.py`.

---

## Submitting a pull request

Every PR must answer these questions in the description:

1. **Which workstream does this belong to?**  
   (Gateway / Memory / Workflow / Tool / Channel / Security / Observability / Config / Skill / Workspace)

2. **Does this change `user_id` boundary logic?**  
   If yes: explain which enforcement point is affected and how the audit is updated.

3. **Does this change the Prompt token structure?**  
   If yes: describe which prompt blocks are affected.

4. **Does this change the memory write path?**  
   If yes: confirm that `MemoryWriteGate` behaviour is unchanged or document the change.

5. **Does this introduce a new side-effect tool?**  
   If yes: confirm it is added to `ToolSpec` with `side_effect_level` set correctly.

6. **Does this require a new ADR or doc update?**

Template is in `.github/PULL_REQUEST_TEMPLATE.md`.

---

## Architecture decision records (ADRs)

All significant design decisions are documented in `docs/adr/`.

Before implementing a non-trivial change, check whether an ADR already exists.  
If your change contradicts an existing ADR, open a discussion first.

Naming: `ADR-NNN-short-description.md`

---

## Backlog tasks

Backlog items live in `docs/backlogs/`.  
Each file describes a concrete, scoped task with acceptance criteria.

To claim a task: leave a comment on the corresponding GitHub issue.

---

## Definition of done

A contribution is complete when **all** of the following are true:

- [ ] Code compiles and all existing tests pass
- [ ] New code has tests covering the main path and at least one error path
- [ ] Relevant `docs/architecture/*.md` is updated (if the change affects a documented component)
- [ ] If a new design decision was made: an ADR is added or an existing one is updated
- [ ] `trace_id` propagation is unchanged (or explicitly noted as changed)
- [ ] Backward compatibility is documented if broken
- [ ] The PR description answers all six questions above

---

## Things not to do

- Do not make cross-module refactors without a backlog task and an ADR.
- Do not modify `user_id` boundary logic without updating the security audit path.
- Do not use prompt patching to work around a structural protocol problem.
- Do not add a side-effect tool without a `ToolSpec` entry and policy review.
- Do not commit real API keys, passwords, or tokens.
