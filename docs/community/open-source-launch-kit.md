# Open Source Launch Kit

This document defines the launch-grade documentation and product showcase standard for Promethea.

## Launch Objectives

- Make first-time users complete a successful run in 10 minutes.
- Make developers evaluate architecture fit in 15 minutes.
- Make maintainers handle issues and contributions with clear policies.
- Make demos reproducible for community talks and release posts.

## Information Architecture (Release Standard)

Use this order in public communication surfaces (README, docs landing page, launch post):

1. One-line product positioning.
2. Why it exists (problem and differentiation).
3. 10-minute quickstart.
4. Core architecture and trust model.
5. Real demo scenarios.
6. API/CLI reference entry points.
7. Community and governance links.
8. Security/reporting policy.

## README Quality Bar

The top-level README must always include:

- What Promethea is and is not.
- Local run commands with minimum required config.
- Links to docs hub, roadmap, governance, security, contributing.
- Concrete feature claims mapped to verifiable endpoints or commands.
- A quick “try these commands” block for immediate proof.

## Showcase Quality Bar

The product showcase in UI/CLI should demonstrate:

- Runtime observability: status + doctor + metrics.
- Reasoning controllability: watch + steer + stop.
- Trust and auditability: recall traces + security report + workflow state.

### Demo Command Set

```bash
promethea status base
promethea status services
promethea doctor run

promethea reasoning list
promethea reasoning watch <tree_id>
promethea reasoning steer <tree_id> "focus constraints"
promethea reasoning stop <tree_id> --reason "manual intervention"

promethea memory recall-runs --limit 10
promethea workflow list
promethea security report --limit 50
```

## Release Checklist

- Product narrative is consistent across README, docs, and UI copy.
- Quickstart commands are tested on a clean environment.
- All new endpoints/commands are documented and linked.
- UI showcase text is i18n-compatible.
- Community docs are visible: `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`, `GOVERNANCE`.
- Changelog entry is ready.

## Competitive Patterns Learned From Successful OSS Projects

- Strong “developer-first” README with immediate value and docs depth.
- Clear separation of “quickstart” vs “deep architecture”.
- Stable docs map for multiple audiences (users vs maintainers/integrators).
- Community governance surfaced early, not buried.
- Demo-friendly command paths that are copy/paste-ready.

## References

- FastAPI repository README: https://github.com/tiangolo/fastapi
- Supabase repository README: https://github.com/supabase/supabase
- Open WebUI repository README: https://github.com/open-webui/open-webui
- Streamlit repository README: https://github.com/streamlit/streamlit
- GitHub Docs: About READMEs: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes
- Open Source Guides (best practices): https://opensource.guide/best-practices/
