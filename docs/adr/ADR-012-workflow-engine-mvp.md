# ADR-012: Workflow Engine MVP

- Status: Accepted
- Date: 2026-03-12
- Backlog: 012

## Context

Promethea needs resumable long-running task execution beyond single-turn chat. Existing runtime primitives (reasoning, memory, workspace) are present but not composed as a durable workflow layer.

## Decision

Implement a linear Workflow Engine MVP in gateway runtime:

- canonical schema: `WorkflowDefinition`, `WorkflowRun`, `WorkflowStep`, `Checkpoint`
- lifecycle operations: start/resume/pause/retry/approve/checkpoint
- step runner with MVP step types and approval gate
- workspace artifact writes from `artifact_step`
- gateway protocol and HTTP routes for workflow operations

## Rationale

This is the smallest slice that enables recoverable execution while avoiding a full DAG/BPM system too early.

## Consequences

Positive:

- workflow runs can be paused and resumed
- failed steps can be retried
- checkpoints provide inspectable recovery boundaries
- approval gate introduces human-in-the-loop control

Tradeoffs:

- only linear workflows are supported in MVP
- in-memory run store is not durable across process restart
- tool and memory steps are intentionally conservative in MVP behavior

## Follow-ups

- durable workflow state storage
- richer dependency graph support
- UI inspector for workflow timelines and approvals
- stricter policy integration for side-effect steps
