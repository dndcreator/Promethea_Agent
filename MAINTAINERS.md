# Maintainers

This file describes maintainer responsibilities and review ownership.

## Maintainer Responsibilities

- Protect runtime correctness and user-boundary safety.
- Review PRs for behavior regressions, security risks, and protocol drift.
- Keep docs and tests aligned with shipped behavior.
- Triage critical issues and coordinate release readiness.

## Review Ownership (Code Areas)

- Gateway runtime and protocol:
  - `gateway/`, `gateway_integration.py`, `conversation_core.py`
- Memory system:
  - `memory/`, `gateway/memory_service.py`
- Tooling and sandbox:
  - `agentkit/`, `gateway/tool_service.py`, `gateway/tools/`
- Channels and clients:
  - `channels/`, `promethea_cli/`, `UI/`
- Documentation and governance:
  - `docs/`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`

## SLA (Best Effort)

- Initial triage for critical issues: within 72 hours.
- PR first response target: within 5 business days.

## Becoming a Maintainer

A contributor can be invited as maintainer after sustained high-quality contributions across:
- correctness and testing
- protocol/documentation discipline
- security and boundary awareness
