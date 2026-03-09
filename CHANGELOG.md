# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]
### Added
- Open-source baseline docs: `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`.
- GitHub templates: issue templates and PR template.
- CI workflow for test + coverage artifact upload.
- Unified local test runner (`tests/run_all_tests.py`) and improved test docs.

### Changed
- Pytest/coverage baseline configured for consistent local/CI runs.
- Reasoning template tests switched to deterministic local temp directories to avoid platform ACL flakes.

## [0.1.0]
### Added
- Initial public project structure.
