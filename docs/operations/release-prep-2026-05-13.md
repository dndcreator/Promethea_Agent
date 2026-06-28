# Release Preparation Status - 2026-05-13

This note records release-preparation checks for the current public preview candidate.

## Documentation Minimum Set

Present:
- `README.md`
- `QUICK_START.md`
- `RELEASE_NOTES.md`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `docs/README.md`
- `docs/release-checklist.md`
- `docs/operations/release-readiness.md`
- `docs/configuration.md`
- `docs/testing-strategy.md`
- `docs/ui-overview.md`
- `docs/architecture/memory-model.md`

## Release-Critical Notes

- Neo4j remains the recommended backend for the intended graph-memory experience.
- Fallback memory backends are explicit alternatives, not silent replacements for Neo4j.
- User configuration is split into sensitive env values, basic config, and advanced config.
- `memory/raw_log.jsonl` and `memory/raw_log.state.json` are L0 memory state, not disposable logs.
- Test artifacts should be confined to `.tmp/pytest-runtime/`.
- Local user data and secrets must not be committed: `.env`, `config/users/`, `logs/`, `workspace/`, UI dependencies, and temp artifacts.

## Local Workspace Findings

Untracked historical test-artifact directories are present locally and ignored by git:
- `.pytest-content-tools/`
- `.pytest-cron-tools/`
- `.pytest-node-tools/`
- `tmp_fs_tests/`
- `tmp_reasoning_template/`
- `_pytest_case_tmp/`
- `_pytest_session_tmp/`

They are not release source files. Remove them manually before packaging only if you want a clean local tree; do not use broad delete commands.

## Required Manual Evidence Before Tag

- Web UI manual smoke: login/register, chat, file attachment, global search, memory inspector, workflow inspector, settings save.
- Neo4j-on first-run path.
- Neo4j-off first-run path with explicit backend guidance.
- One local startup from a clean checkout or clean copy.

## Automated Evidence Collected

- `cd UI; npm run build`: passed.
- `python -m pytest tests/test_files_routes.py tests/test_chat_routes_args_resilience.py tests/test_config_routes_contract.py tests/test_prompt_assembler.py tests/test_user_secrets.py tests/test_prompt_policy_router.py -q`: 29 passed.
- `git diff --check`: no whitespace errors; Windows line-ending warnings only.
