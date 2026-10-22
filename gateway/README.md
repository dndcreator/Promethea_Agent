# Gateway Module

`gateway` is the runtime orchestrator. It wires the major subsystems together: HTTP routes, conversation state, configuration, memory, tools, workflow, reasoning, and runtime events.

Its job is orchestration. Domain details should stay in the relevant service layer instead of accumulating in routes or one central file.

## Key Files

- `gateway/app.py`: lifecycle and startup order
- `gateway/server.py`: main server orchestration entry
- `gateway/config_service.py`: config merge, update, and reset logic
- `gateway/conversation_service.py`: conversation/session orchestration
- `gateway/delegation.py`: optional bounded child admission and lifetime; children reuse ConversationService/ActionService, Registry, policy and Runtime events
- `gateway/background_agents.py`: persistent child descriptors and FIFO message semantics over TaskService/TaskRuntime; no separate scheduler or model loop
- `gateway/agent_messages.py`: direct-parent report admission, Runtime settlement and bounded inbox projections; TaskService owns message persistence, MessageManager commits conversation receipts, and TaskRuntime owns notification execution
- `gateway/action/checkpoint.py`: Action checkpoint serialization and restoration, with uncertain effects returned as Observations rather than replayed
- `gateway/memory_service.py`: memory integration facade
- `gateway/capability_service.py`: governed execution boundary for tools, computer capabilities, policy, and approval
- `gateway/tools/projection.py`: stateless capability snapshot content and candidate ranking; Registry, authorization, snapshot identity, and events remain service-owned
- `gateway/task_service.py`: durable task and run state
- `gateway/workbench_projection.py`: user-facing projection over runtime events
- `gateway/public_contracts.py`: transport-neutral public contract source
- `gateway/workflow_engine.py`: workflow definitions, runs, checkpoints, and recovery
- `gateway/workflow_definition.py`: definition validation and dependency selection, without run transitions
- `gateway/workflow_state_store.py`: workflow snapshot encoding and atomic storage, without a second live state cache
- `gateway/memory_extraction.py`: candidate extraction and verification; write gates and queues remain in MemoryService
- `gateway/reasoning_evaluation.py`: bounded observation samples and model evaluations; outcome adoption and tree state remain in ReasoningService
- `gateway/org_context_extraction.py`: organization document chunking and extraction; membership, review and publication remain in OrgContextService
- `gateway/config_gateway_handler.py`: configuration request adaptation over the currently injected ConfigService
- `gateway/events.py`: event bus
- `gateway/protocol.py`: protocol data structures

## Architecture And Flow

1. Request enters HTTP routes.
2. Route delegates to a gateway service.
3. Services pass data through stable protocol shapes.
4. Response is returned with logging, metrics, and normalized errors.

Design principles:

- clear service boundaries
- user context across the full path
- replaceable internals with stable external behavior

## Simple Example

Settings save flow:

1. UI calls `POST /api/config/update`.
2. Route delegates to `ConfigService`.
3. `ConfigService` validates and merges updates.
4. The user config file is persisted.
5. The UI refreshes from the saved state.

## Operational Notes

- Prefer a single update path for config writes.
- Keep route logic thin.
- Never bypass `user_id`-based isolation checks.

## Change Notes

- Add new features in the service layer first, then expose via routes.
- When protocol fields change, sync frontend and tests.
- Re-run turn/session regression tests after conversation changes.
