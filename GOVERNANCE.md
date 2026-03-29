# Governance

This document defines how Promethea makes technical and project decisions as an open-source runtime project.

## Scope

Governance applies to:
- Runtime protocol and API contracts
- Security boundaries and multi-user isolation
- Memory, workflow, and tool execution behavior
- Release quality gates and compatibility policy

## Roles

- Project Owner
  - Final decision-maker for roadmap and release direction.
- Maintainers
  - Review and merge code, enforce quality and security constraints.
- Contributors
  - Propose and implement changes via issues and pull requests.

## Decision Model

- Default model: maintainer consensus.
- Escalation model: project owner decision when consensus cannot be reached.
- All non-trivial architecture changes require:
  - updated docs in `docs/architecture/` or ADR in `docs/adr/`
  - explicit compatibility notes if behavior changes.

## Change Classes

- Minor: internal refactor, test/doc updates, no contract impact.
- Contract-affecting: HTTP/WS/protocol/config schema change.
- Security-affecting: user boundary, sandbox, memory/tool policy changes.

Contract-affecting and security-affecting changes require at least one maintainer approval plus updated tests.

## Security and Boundary Rules

- Cross-user access is forbidden by default.
- Env-only secrets are never persisted to per-user config files.
- Side-effect tools must be classified and policy-governed.

## Release Governance

A release is eligible only when:
- CI passes
- Readiness checks are green or accepted with explicit degraded notes
- Backward-compatibility notes are documented
- Security-impacting changes are reviewed by maintainers

## Code of Conduct

Community interactions are governed by `CODE_OF_CONDUCT.md`.
