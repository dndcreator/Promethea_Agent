# CLI Reference (v1)

This document describes `promethea` CLI as a protocol client of the runtime.

## Positioning

CLI is both:
- A human-facing front end (terminal-first assistant usage).
- An automation/protocol harness (for scripts, CI, and agent-to-agent calls).

CLI is not a separate runtime. The backend runtime remains the source of truth.

## Read This If

- You want to use Promethea without the Web UI.
- You want stable commands for smoke tests and CI.
- You want to confirm that protocol surfaces are actually callable.

## Quick Start

```bash
# auth
promethea auth register <username> <password>
promethea auth login <username> <password>

# one chat turn
promethea chat send "è¯·æ»ç»ä»å¤©çå·¥ä½" --stream

# inspect tools and services
promethea status official-tools
promethea status services
```

## Command Groups

### 1) Chat and Sessions

- `chat send`
- `chat chat-confirm`
- `ask`
- `followup`
- `sessions list`
- `sessions show <session_id>`

Use this group when your goal is "talk to the agent now".

### 2) Config and Runtime Preferences

- `config get`
- `config effective`
- `config update`
- `config reset`
- `config switch-model`
- `config ui-schema`
- `config contract`
- `config runtime`
- `config runtime-scoped`

Use this group when your goal is "change behavior".

### 3) Memory

- `memory capabilities`
- `memory graph`
- `memory entries-list`
- `memory entries-create`
- `memory entries-update`
- `memory entries-delete`
- `memory recall-runs`
- `memory recall-inspect`

Use this group when your goal is "inspect or maintain long-term memory".

### 4) Workflow

- `workflow define`
- `workflow list`
- `workflow start`
- `workflow run`
- `workflow pause`
- `workflow resume`
- `workflow retry`
- `workflow approve`
- `workflow checkpoints`

Use this group when your goal is "long-running or resumable tasks".

### 5) Tools and Runtime Introspection

- `call` (generic tool invoke)
- `status tools`
- `status official-tools`
- `ops capabilities`
- `ops protocol`
- `ops methods`
- `ops http-contracts`
- `ops surfaces`
- `ops runbook`

Use this group when your goal is "what can this runtime do right now".

### 6) Voice

Experimental/provider-dependent in the current preview. These commands are not part of the supported DeepSeek-only setup path because DeepSeek chat APIs do not provide STT/audio transcription.

- `voice capabilities`
- `voice stt <file>`
- `voice tts <text>`
- `voice turn <text>`
- `voice ptt <file>`

Use this group only when an OpenAI-compatible audio transcription provider is configured.

## Example User Journeys

### Journey A: "Search web then write report"

```bash
promethea chat send "è¯·è°ç  OpenAI ææ°æ¨¡åï¼å¹¶å¨ workspace åä¸ä»½ markdown æ¥å" --stream
promethea workflow list
promethea status tools
```

### Journey B: "Check if runtime is integration-ready"

```bash
promethea ops surfaces
promethea ops protocol
promethea ops http-contracts
promethea doctor run
```

### Journey C: "Memory quality check"

```bash
promethea memory entries-list --limit 20
promethea memory recall-runs --limit 10
promethea memory recall-inspect <request_id>
```

## Capability Boundary

CLI can drive almost all backend capabilities already exposed by HTTP/WS contracts.

Still UI-heavy today:
- Dense visual graph exploration.
- Highly interactive drag/drop or modal workflows.
- Theme/avatar UX presentation.

These are presentation differences, not core capability gaps.

## Operational Notes

1. API keys and provider secrets remain env-managed.
2. Side-effect tools may require approval depending on policy.
3. Dependency state (MCP/Neo4j/provider reachability) changes callable surface.
4. CLI output is useful for both humans and machine parsing, but for strict contracts prefer `ops http-contracts` and route schemas.

## Troubleshooting

- If command exists but fails: run `promethea status services` first.
- If tool call denied: inspect policy using `promethea config tool-policy`.
- If memory behavior odd: inspect `memory recall-runs` + `memory recall-inspect`.
- If voice fails: confirm that an audio transcription provider is configured; DeepSeek-only chat configuration is not enough for voice input.

## Suggested Smoke Suite

For CI or release gate, keep these as minimal checks:
- one chat turn
- official tools list
- workflow start + run
- config effective
- ops protocol + http-contracts
