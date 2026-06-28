# Gateway Module

`gateway` is the runtime orchestrator. It wires the major subsystems together: HTTP routes, conversation state, configuration, memory, tools, workflow, reasoning, and runtime events.

Its job is orchestration. Domain details should stay in the relevant service layer instead of accumulating in routes or one central file.

## Key Files

- `gateway/app.py`: lifecycle and startup order
- `gateway/server.py`: main server orchestration entry
- `gateway/config_service.py`: config merge, update, and reset logic
- `gateway/conversation_service.py`: conversation/session orchestration
- `gateway/memory_service.py`: memory integration facade
- `gateway/tool_service.py`: tool-call coordination
- `gateway/workflow_engine.py`: workflow definitions, runs, checkpoints, and recovery
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
