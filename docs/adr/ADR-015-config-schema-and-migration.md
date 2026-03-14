# ADR-015: Config Schema Versioning and Migration Baseline

- Status: Accepted
- Date: 2026-03-13
- Backlog: 015

## Context

Configuration complexity is increasing across runtime, user preferences, security, channels, workflow, and skills.
Without versioning and migration, schema evolution can break user configs and runtime stability.

## Decision

Introduce a minimal but executable config governance baseline:

1. Add `config_version` as a root marker.
2. Add migration module with deterministic step execution.
3. Add deprecation warning collection/reporting.
4. Add scoped config access methods to avoid pushing oversized config objects into runtime paths.
5. Start boundary separation through compatibility sections:
   - `runtime_config`
   - `user_preferences`
   - `security_config`
   - `channel_config`

## Consequences

Positive:
- Config evolution becomes trackable and safer.
- Legacy configs can be upgraded programmatically.
- Runtime modules can request only the config subset they need.

Trade-offs:
- Temporary coexistence of legacy and new fields.
- Additional migration maintenance over time.

## Follow-ups

- Expand migration steps for future schema revisions.
- Gradually move more modules to scoped accessor usage.
- Add doctor panel exposure for migration/deprecation reports.
