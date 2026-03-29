# Testing Strategy

This project uses layered testing to balance speed, confidence, and product realism.

## 1. Test Layers

### Layer A: Unit Tests
- Goal: verify local logic with deterministic inputs.
- Typical modules:
  - policy checks
  - model mappers
  - serialization contracts

### Layer B: Service Contract Tests
- Goal: verify service APIs and response shapes.
- Typical modules:
  - config service
  - tool service
  - workflow engine
  - protocol surface contracts

### Layer C: Business Journey Tests
- Goal: simulate realistic user-facing workflows across multiple services.
- Typical paths:
  - `chat -> tool confirmation -> resume`
  - `batch -> workflow.define -> workflow.start -> workspace artifacts`
  - `tools.list -> tool.call`
  - `voice ptt -> stt -> turn -> optional tts`

## 2. Why Business Journey Tests Matter

Pure unit tests can pass while user-facing flows fail due to:
- integration wiring issues
- session/state transition bugs
- policy or permission mismatches
- payload shape drift across boundaries

Business tests are designed to catch these issues early.

## 3. Current High-Value Journey Suites

- `tests/test_mvp_business_smoke.py`
- `tests/test_business_journeys.py`
- `tests/test_voice_routes.py`

## 4. Gate Recommendations

Before release, require:
1. Core contract tests passing.
2. Business journey suites passing.
3. Readiness endpoints healthy or explicitly acknowledged degradation.

## 5. CI Prioritization

Fast PR stage:
- unit + contract tests

Main branch stage:
- business journeys
- readiness/report generation

Pre-release stage:
- full test matrix + manual sanity checklist

## 6. Known Constraints

- External providers (OpenAI / ElevenLabs / Neo4j / MCP remote) should be mocked in CI.
- Local environment tests should avoid hard network requirements unless explicitly marked integration.

## 7. Next Expansion Targets

- Channel adapter end-to-end fixtures for major official channels.
- More negative-path tests for memory/reasoning degradation reason codes.
- Release-grade scenario replay packs for regression prevention.

