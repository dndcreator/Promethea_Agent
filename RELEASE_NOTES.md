# Release Notes

## Public Preview Release Candidate

This release candidate focuses on making Promethea usable as a local-first cognitive agent runtime with a modern Web UI, graph-first memory, backend-aware first-run behavior, and release-ready documentation.

## Highlights

- Promotional bilingual homepage for Promethea's positioning: beyond memory, toward cognition.
- Vite Web UI connected to the gateway startup script.
- Backend-aware first-run auth flow:
  - Neo4j remains the default and core graph backend.
  - If Neo4j is configured but unavailable, registration is blocked with a clear message instead of silently falling back.
  - The login screen can enter setup/diagnostics mode before sign-in.
- File upload and attachment flow:
  - Text-like files can be extracted and attached to chat.
  - Image files are stored and may use OCR when optional dependencies are available.
  - Stored-only attachments are explicitly described as unavailable to the model instead of being invented.
- Global search across sessions and uploaded files.
- Workflow inspector for definitions, personal runs, recovery, pause/resume, and checkpoints.
- Enterprise Brain visibility now follows `org_brain.enabled`; disabled enterprise features are hidden from the UI.
- Memory visualization and inspector readability improvements.
- Test artifact policy confines runtime test files under `.tmp/pytest-runtime/`.
- User configuration is split into sensitive env values, basic config, and advanced config.
- Prompt assembly uses explicit prompt blocks, with policy routing prepared for need-based block selection.
- `memory/raw_log.jsonl` is documented as the L0 memory layer, not disposable test output.

## Important Behavior

- Full graph-memory behavior requires Neo4j.
- Fallback memory backends remain available, but they are explicit choices, not silent replacements for the default Neo4j experience.
- Changing backend configuration should be followed by a restart.
- Playwright browser control requires installing Playwright browsers separately.
- Multimodal support currently means file storage, text extraction, and optional OCR; it is not guaranteed native vision input for every model/provider.
- Voice input is not part of the supported preview release surface. The current experimental push-to-talk route depends on an OpenAI-compatible audio transcription provider; a DeepSeek-only chat configuration does not provide STT/audio transcription.

## Verification

Release-focused checks run during preparation:

- `python -m pytest`: 500 passed, 5 skipped
- `npm run build` in `UI/`: TypeScript and Vite production build passed
- `npm run lint` in `UI/`: ESLint passed

Manual checks still required before a stable tag:

- Web UI smoke test: first-run status, registration/login, chat, file attachment, global search, memory inspector, workflow inspector, settings save, enterprise feature visibility.
- Neo4j-on and Neo4j-off first-run flows.

## Known Limitations

- This is a public preview / release candidate, not a final stable commercial release.
- Neo4j is strongly recommended for the intended graph-structured memory experience.
- Some advanced integrations depend on optional local services or third-party credentials.
- Frontend development/build can be affected by local Windows Node/esbuild execution policy; verify in a normal local PowerShell environment.
- Voice endpoints may appear in the internal API surface, but they are experimental/provider-dependent and should not be presented as a ready user feature in this release.

## Upgrade Notes

- Copy new environment variables from `env.example` if your local `.env` is old.
- Restart the gateway after changing memory backend or enterprise feature switches.
- Do not commit files under `config/users/`, `logs/`, `workspace/`, `UI/node_modules/`, `.tmp/`, or local test artifact directories.
- Treat `memory/raw_log.jsonl` and `memory/raw_log.state.json` as runtime memory state. Do not clean them as generic logs.
