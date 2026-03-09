# Contributing Guide

Thanks for contributing.

## Development Setup
1. Create virtualenv and install deps:
   - `pip install -e .[dev]`
2. Run tests:
   - `python -m pytest -q`
3. Optional coverage:
   - `python -m pytest --cov=. --cov-report=term-missing -q`

## Branch / PR Rules
- Keep PRs focused and small.
- Add or update tests for behavior changes.
- Avoid mixing refactor + feature + bugfix in one PR.
- Include a short risk note in PR description.

## Testing Expectations
- Unit/integration tests should pass before PR.
- Live tests should be guarded by `PROMETHEA_LIVE_TEST=1`.
- New tools should include at least one service-level test.

## Commit Message Style
- Use clear prefix, e.g.:
  - `feat: ...`
  - `fix: ...`
  - `test: ...`
  - `docs: ...`

## Security
Please do not post secrets or tokens in issues/PRs.
For vulnerabilities, follow `SECURITY.md`.
