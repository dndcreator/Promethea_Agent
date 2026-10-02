# Protocol Boundaries

Promethea keeps Agent, Reasoning, Memory, Workflow, Context, Session, and model
execution inside one Python runtime. Python services call each other directly;
these internal interfaces are not network contracts.

## Supported External Boundaries

### UI, Browser, or IDE to Runtime

- HTTP API: `/api/*`
- HTTP schema: `/openapi.json`
- Streaming chat: SSE from `/api/chat`
- Bidirectional runtime messages: `/gateway/ws/{device_id}`

HTTP and WebSocket requests converge on the Gateway dispatcher. A transport
adapter may normalize input, but it must not implement core runtime behavior.

### TypeScript SDK or External Client to Runtime

Use `/openapi.json` to generate endpoint clients. The smaller
`/api/ops/schema` document publishes transport-neutral core objects:

- `RunRequest` and `RunResponse`
- `Session`
- `Event`
- `ToolCall` and `ToolResult`
- `Error`
- public `Task` and `TaskRun` read models
- `WorkbenchSnapshot` and normalized activities

These objects are additive within protocol version 1.0. Authentication supplies
user identity; clients must not send Python runtime objects or internal service
state.

TypeScript clients should generate their HTTP types from `/openapi.json` with
their normal OpenAPI toolchain. This repository does not maintain a second,
handwritten TypeScript copy of the Python models.

Promethea's checked-in TypeScript bindings are generated from the same Pydantic
models through their JSON Schema representation:

```powershell
python scripts/generate_public_contracts.py
python scripts/generate_public_contracts.py --check
```

The outputs are `contracts/runtime-v1.schema.json` and
the generated files under `UI/src/generated/` and
`sdk/typescript/src/generated/`. CI/tests fail when a generated file is stale.
Endpoint-specific HTTP clients can still be generated from
`/openapi.json`; both sources originate from the same Pydantic models.

## TypeScript SDK

The thin SDK under `sdk/typescript/` is the first external consumer of these
contracts. It owns HTTP request mechanics, SSE parsing, error normalization, and
cancellation. Python Gateway remains the server adapter and Python Core retains
all runtime decisions.

The initial SDK intentionally omits Gateway WebSocket support. The running route
is `/gateway/ws`, while current surface discovery advertises
`/gateway/ws/{device_id}`, and browser authentication has no stable public
contract. Those transport details should be reconciled before exposing a stable
SDK API.

Chat SSE uses standard `id`, `event`, and `data` framing. The JSON data retains
the legacy `type` and `content` fields used by the current UI and adds stable
event metadata (`event_id`, `event_type`, `occurred_at`, `seq`, `request_id`,
and `source`). This stream is request-bound and is not advertised as resumable.

Workbench uses its narrower SSE projection stream rather than exposing Python
service records. The SDK owns connection parsing, cancellation, reconnection,
and cursor forwarding. Task state transitions, event persistence, projection,
authorization, and revision checks remain in Python.

Workbench workflow, memory-write, and recall entries are explicit public
summaries. Raw attempts, idempotency keys, recalled memory contents, conflict
candidate contents, and recovery ownership remain available only to their
own authorized runtime APIs and are not part of `WorkbenchSnapshot`.

### External Tool or Plugin to Runtime

MCP is the preferred cross-language tool boundary. External MCP providers are
discovered into the MCP transport registry and synchronized into `ToolRegistry`;
local and extension Python tools are discovered directly into the same registry
and execute in process through `CapabilityService`. A plugin should not
call Memory, Reasoning, or Workflow implementation classes directly.

## Boundary Ownership

| Concern | Canonical source |
| --- | --- |
| HTTP paths and payloads | FastAPI routes and `/openapi.json` |
| Public runtime objects | `gateway/public_contracts.py` and `/api/ops/schema` |
| WebSocket envelopes and methods | `gateway/protocol.py` and `/api/ops/methods` |
| Runtime surface discovery | `/api/ops/surfaces` |
| External tools | MCP registry and `CapabilityService` |
| Python backend substitution | ordinary Python interfaces |

`gateway/protocol.py` still contains some internal pipeline models for backward
compatibility. They are not part of `/api/ops/schema` and must not be used by
generated SDKs. They can be moved into an internal module later without changing
the public protocol.

The streaming implementation in `gateway/http/routes/chat.py` still coordinates
some runtime services directly, but it now builds the same `RunContext` and
propagates the same public request hints as the non-streaming Gateway path.
Moving that orchestration behind the dispatcher is a valid follow-up, but is
intentionally outside this compatibility-focused change.
