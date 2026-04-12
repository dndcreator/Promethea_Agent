# Showcase Playbook

This playbook is for product demos, launch videos, and open-source onboarding sessions.

## Audience Tracks

- Builder track: architecture, API, workflow, safety.
- Operator track: status, doctor, metrics, audit.
- End-user track: chat UX, memory continuity, reasoning controls.

## 8-Minute Demo Script

1. Start runtime and open Web UI.
2. Show health and services.
3. Send a complex query that triggers reasoning.
4. Use reasoning panel to steer and stop.
5. Show memory recall runs and workflow list.
6. Show security audit report.
7. Close with docs/governance links and contribution path.

## CLI Script

```bash
promethea status base
promethea status services
promethea doctor run

promethea chat send "Design a migration plan for legacy API auth." --stream
promethea reasoning list
promethea reasoning watch <tree_id>
promethea reasoning steer <tree_id> "Prioritize rollback safety and blast radius."

promethea memory recall-runs --limit 10
promethea workflow list
promethea security report --limit 20
```

## Demo Rules

- Never demo unverified commands.
- Always include one “failure path” and show recovery.
- Always include one trust proof: audit, policy decision, or explicit stop control.
- Keep commands copy/paste-ready.
