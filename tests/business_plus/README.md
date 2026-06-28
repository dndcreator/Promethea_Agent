# Business Plus Tests

`business_plus` stores higher-level business scenario tests. The goal is to keep realistic product flows separate from low-level unit tests.

- Cover real user paths such as `chat -> tool confirm -> execute`, `workflow pause/approve/resume`, and batch orchestration.
- Keep scenarios maintainable: each file should focus on a small number of journeys with clear mocks and shared fixtures.
- Avoid external network dependencies by default so the suite can run locally before release.

## Naming Rules

- File name: `test_business_plus_*.py`
- Test name: `test_business_plus_<scenario>_<expected_result>`

## Temporary Scope

- A single test may cross 2 or more runtime modules, such as `gateway + tool_service + workflow_engine`.
- The target is to validate business path reliability, not every internal boundary.

## Run

```bash
python -m pytest tests/business_plus -q
```
